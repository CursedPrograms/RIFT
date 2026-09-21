// RiftMdns.cs - Zeroconf: publish this instance as _rift._tcp and watch for
// other RIFT instances and ComCentre (_flask-link._tcp) - browsing both is what
// lets DREAM show up in this dashboard without ComCentre knowing anything about
// RIFT. A small responder + browser over multicast UDP (224.0.0.251:5353) using
// just the DNS wire format: PTR (service -> instance), SRV (instance -> host +
// port), TXT and A (host -> address). No Bonjour/Avahi or extra package needed,
// so it behaves the same inside Unity on Windows, Linux and macOS.

using System;
using System.Collections.Generic;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;

namespace Rift
{
    public sealed class RiftMdns : IDisposable
    {
        const ushort TA = 1, TPtr = 12, TTxt = 16, TSrv = 33, TAny = 255;
        const ushort ClassIn = 1, CacheFlush = 0x8000;
        static readonly IPAddress Group = IPAddress.Parse("224.0.0.251");

        readonly RiftConfig cfg;
        readonly RiftPeers peers;
        Socket sock;
        volatile bool running;
        Thread recvThread, queryThread;

        // Only touched from the receive thread.
        readonly Dictionary<string, KeyValuePair<int, string>> srv = new Dictionary<string, KeyValuePair<int, string>>(); // lowercase instance -> (port, host)
        readonly Dictionary<string, string> addrs = new Dictionary<string, string>();                                     // lowercase host -> IPv4
        readonly Dictionary<string, string> instances = new Dictionary<string, string>();                                 // lowercase instance -> original case

        public RiftMdns(RiftConfig cfg, RiftPeers peers)
        {
            this.cfg = cfg;
            this.peers = peers;
        }

        // Returns null on success, else an error message.
        public string Start()
        {
            try
            {
                sock = new Socket(AddressFamily.InterNetwork, SocketType.Dgram, ProtocolType.Udp);
                sock.SetSocketOption(SocketOptionLevel.Socket, SocketOptionName.ReuseAddress, true);
                sock.Bind(new IPEndPoint(IPAddress.Any, 5353));
                var local = IPAddress.Parse(cfg.Ip);
                try { sock.SetSocketOption(SocketOptionLevel.IP, SocketOptionName.AddMembership, new MulticastOption(Group, local)); }
                catch (SocketException) { sock.SetSocketOption(SocketOptionLevel.IP, SocketOptionName.AddMembership, new MulticastOption(Group)); }
                sock.SetSocketOption(SocketOptionLevel.IP, SocketOptionName.MulticastInterface, local.GetAddressBytes());
                sock.SetSocketOption(SocketOptionLevel.IP, SocketOptionName.MulticastLoopback, true);
                sock.SetSocketOption(SocketOptionLevel.IP, SocketOptionName.MulticastTimeToLive, 255);
                sock.ReceiveTimeout = 500;
            }
            catch (Exception e) when (e is SocketException || e is FormatException)
            {
                return e.Message;
            }
            running = true;
            recvThread = new Thread(ReceiveLoop) { IsBackground = true, Name = "rift-mdns-recv" };
            queryThread = new Thread(QueryLoop) { IsBackground = true, Name = "rift-mdns-query" };
            recvThread.Start();
            queryThread.Start();
            return null;
        }

        public void Dispose()
        {
            if (!running) return;
            running = false;
            Send(AnnouncePacket(0)); // goodbye
            recvThread?.Join(1500);
            queryThread?.Join(1500);
            try { sock.Close(); } catch (SocketException) { }
        }

        // ---- building ----

        static void U16(List<byte> b, int v) { b.Add((byte)(v >> 8)); b.Add((byte)v); }
        static void U32(List<byte> b, long v) { U16(b, (int)(v >> 16) & 0xffff); U16(b, (int)v & 0xffff); }

        static void Name(List<byte> b, string name)
        {
            foreach (var label in name.TrimEnd('.').Split('.'))
            {
                var bytes = Encoding.UTF8.GetBytes(label);
                b.Add((byte)bytes.Length);
                b.AddRange(bytes);
            }
            b.Add(0);
        }

        static void Record(List<byte> b, string name, int type, int cls, long ttl, List<byte> rdata)
        {
            Name(b, name);
            U16(b, type);
            U16(b, cls);
            U32(b, ttl);
            U16(b, rdata.Count);
            b.AddRange(rdata);
        }

        static List<byte> Header(int flags, int qd, int an, int ar)
        {
            var b = new List<byte>();
            U16(b, 0); U16(b, flags); U16(b, qd); U16(b, an); U16(b, 0); U16(b, ar);
            return b;
        }

        byte[] AnnouncePacket(long ttl)
        {
            string service = "_rift._tcp.local", instance = cfg.Name + "." + service, host = cfg.Name + ".local";
            var p = Header(0x8400, 0, 1, 3);

            var ptr = new List<byte>();
            Name(ptr, instance);
            Record(p, service, TPtr, ClassIn, ttl, ptr);

            var srvData = new List<byte>();
            U16(srvData, 0); U16(srvData, 0); U16(srvData, cfg.Port);
            Name(srvData, host);
            Record(p, instance, TSrv, CacheFlush | ClassIn, ttl, srvData);

            var txt = new List<byte>();
            var entry = Encoding.UTF8.GetBytes("role=fleet_manager");
            txt.Add((byte)entry.Length);
            txt.AddRange(entry);
            Record(p, instance, TTxt, CacheFlush | ClassIn, ttl, txt);

            var a = new List<byte>(IPAddress.Parse(cfg.Ip).GetAddressBytes());
            Record(p, host, TA, CacheFlush | ClassIn, ttl, a);
            return p.ToArray();
        }

        static byte[] QueryPacket(string name, int type)
        {
            var p = Header(0, 1, 0, 0);
            Name(p, name);
            U16(p, type);
            U16(p, ClassIn);
            return p.ToArray();
        }

        void Send(byte[] packet)
        {
            try { sock.SendTo(packet, new IPEndPoint(Group, 5353)); }
            catch (SocketException) { }
            catch (ObjectDisposedException) { }
        }

        // ---- parsing ----

        sealed class Rec
        {
            public string Name = "", Target = "", Addr = "";
            public int Type, Ttl, Port;
        }

        static int Rd16(byte[] b, int p)
        {
            if (p + 2 > b.Length) throw new IndexOutOfRangeException();
            return (b[p] << 8) | b[p + 1];
        }

        // Reads a (possibly compressed) name at p; advances p past it.
        static string ReadName(byte[] b, ref int p)
        {
            var labels = new List<string>();
            int pos = p;
            bool jumped = false;
            int hops = 0;
            while (true)
            {
                if (pos >= b.Length) throw new IndexOutOfRangeException();
                int len = b[pos];
                if (len == 0) { pos++; break; }
                if ((len & 0xc0) == 0xc0)
                {
                    if (pos + 1 >= b.Length || ++hops > 32) throw new IndexOutOfRangeException();
                    if (!jumped) p = pos + 2;
                    jumped = true;
                    pos = ((len & 0x3f) << 8) | b[pos + 1];
                }
                else
                {
                    if (pos + 1 + len > b.Length) throw new IndexOutOfRangeException();
                    labels.Add(Encoding.UTF8.GetString(b, pos + 1, len));
                    pos += 1 + len;
                }
            }
            if (!jumped) p = pos;
            return string.Join(".", labels);
        }

        static void Parse(byte[] b, List<KeyValuePair<string, int>> questions, List<Rec> recs)
        {
            int qd = Rd16(b, 4), total = Rd16(b, 6) + Rd16(b, 8) + Rd16(b, 10);
            int p = 12;
            for (int i = 0; i < qd; i++)
            {
                string n = ReadName(b, ref p);
                questions.Add(new KeyValuePair<string, int>(n, Rd16(b, p)));
                p += 4;
            }
            for (int i = 0; i < total; i++)
            {
                var r = new Rec { Name = ReadName(b, ref p) };
                r.Type = Rd16(b, p);
                r.Ttl = (Rd16(b, p + 4) << 16) | Rd16(b, p + 6);
                int rdlen = Rd16(b, p + 8), rd = p + 10;
                if (rd + rdlen > b.Length) throw new IndexOutOfRangeException();
                if (r.Type == TPtr) { int q = rd; r.Target = ReadName(b, ref q); }
                else if (r.Type == TSrv) { r.Port = Rd16(b, rd + 4); int q = rd + 6; r.Target = ReadName(b, ref q); }
                else if (r.Type == TA && rdlen == 4) r.Addr = b[rd] + "." + b[rd + 1] + "." + b[rd + 2] + "." + b[rd + 3];
                recs.Add(r);
                p = rd + rdlen;
            }
        }

        static bool IsBrowsedService(string lname) => lname == "_rift._tcp.local" || lname == "_flask-link._tcp.local";
        static bool IsBrowsedInstance(string lname) => lname.Contains("._rift._tcp.local") || lname.Contains("._flask-link._tcp.local");

        void PublishPeers()
        {
            foreach (var kv in srv)
            {
                string instance = instances[kv.Key];
                string shortName = instance.Split('.')[0];
                if (shortName == cfg.Name) continue;
                if (!addrs.TryGetValue(kv.Value.Value.ToLowerInvariant(), out var ip)) continue;
                peers.Set(shortName, "http://" + ip + ":" + kv.Value.Key);
            }
        }

        void HandlePacket(byte[] packet)
        {
            var questions = new List<KeyValuePair<string, int>>();
            var recs = new List<Rec>();
            Parse(packet, questions, recs);

            string service = "_rift._tcp.local", instance = (cfg.Name + "." + service).ToLowerInvariant(), host = (cfg.Name + ".local").ToLowerInvariant();
            foreach (var q in questions)
            {
                string n = q.Key.ToLowerInvariant();
                int t = q.Value;
                if ((n == service && (t == TPtr || t == TAny)) || (n == instance && (t == TSrv || t == TTxt || t == TAny)) || (n == host && (t == TA || t == TAny)))
                {
                    Send(AnnouncePacket(120)); // someone is asking about us
                    break;
                }
            }

            foreach (var r in recs)
            {
                string lname = r.Name.ToLowerInvariant();
                if (r.Type == TPtr && IsBrowsedService(lname))
                {
                    string shortName = r.Target.Split('.')[0];
                    if (r.Ttl == 0) peers.Remove(shortName); // goodbye
                    else if (shortName != cfg.Name)
                    {
                        instances[r.Target.ToLowerInvariant()] = r.Target;
                        if (!srv.ContainsKey(r.Target.ToLowerInvariant())) Send(QueryPacket(r.Target, TSrv));
                    }
                }
                else if (r.Type == TSrv && IsBrowsedInstance(lname))
                {
                    instances[lname] = r.Name;
                    srv[lname] = new KeyValuePair<int, string>(r.Port, r.Target);
                    if (!addrs.ContainsKey(r.Target.ToLowerInvariant())) Send(QueryPacket(r.Target, TA));
                }
                else if (r.Type == TA && r.Addr.Length > 0) addrs[lname] = r.Addr;
            }
            PublishPeers();
        }

        void ReceiveLoop()
        {
            var buf = new byte[9000];
            while (running)
            {
                int n;
                try { n = sock.Receive(buf); }
                catch (SocketException) { continue; }        // timeout: re-check running
                catch (ObjectDisposedException) { break; }
                if (n <= 0) continue;
                try
                {
                    var packet = new byte[n];
                    Array.Copy(buf, packet, n);
                    HandlePacket(packet);
                }
                catch (Exception)
                {
                    // A malformed packet from someone else must never take the responder down.
                }
            }
        }

        void QueryLoop()
        {
            int announced = 0;
            while (running)
            {
                Send(QueryPacket("_rift._tcp.local", TPtr));
                Send(QueryPacket("_flask-link._tcp.local", TPtr));
                if (announced < 3) { Send(AnnouncePacket(120)); announced++; }
                for (int i = 0; i < (announced < 3 ? 10 : 100) && running; i++) Thread.Sleep(100);
            }
        }
    }
}
