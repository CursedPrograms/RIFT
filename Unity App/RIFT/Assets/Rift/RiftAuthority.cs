// RiftAuthority.cs - announces this RIFT instance to a NORA hub as the fleet
// authority, over HTTP/WiFi (default) or a Bluetooth serial link. C#
// counterpart of Fleet/register.py + Fleet/bt_link.py: while RIFT keeps
// heartbeating, NORA defers her /robots response to point at RIFT; if it stops,
// the registration simply expires on her side.

using System;
using System.Collections.Generic;
using System.Net.Http;
using System.Threading;
using System.Threading.Tasks;

namespace Rift
{
    // The fleet-registration half of NORA's Bluetooth protocol: send
    // "H<name>:<cap1,cap2>\n", she replies "OK\n" or "ERR\n".
    //
    // System.IO.Ports isn't part of Unity's default ".NET Standard 2.1" API
    // profile, so it's reached by reflection: this compiles everywhere, and
    // Bluetooth mode simply fails (and is retried) unless the project's
    // "Api Compatibility Level" is set to ".NET Framework".
    sealed class SerialLink : IDisposable
    {
        readonly Type type;
        readonly object port;

        public SerialLink(string portName, int baud)
        {
            type = Type.GetType("System.IO.Ports.SerialPort, System.IO.Ports")
                   ?? Type.GetType("System.IO.Ports.SerialPort, System")
                   ?? throw new NotSupportedException("System.IO.Ports is not available (set Api Compatibility Level to .NET Framework in Unity)");
            port = Activator.CreateInstance(type, portName, baud);
            type.GetProperty("ReadTimeout").SetValue(port, 2000);
            type.GetProperty("WriteTimeout").SetValue(port, 2000);
            type.GetMethod("Open", Type.EmptyTypes).Invoke(port, null);
        }

        public bool Register(string name, string capabilities)
        {
            type.GetMethod("DiscardInBuffer", Type.EmptyTypes).Invoke(port, null);
            type.GetMethod("Write", new[] { typeof(string) }).Invoke(port, new object[] { "H" + name + ":" + capabilities + "\n" });
            var reply = (string)type.GetMethod("ReadLine", Type.EmptyTypes).Invoke(port, null);
            return reply.Trim() == "OK";
        }

        public void Dispose()
        {
            try { type.GetMethod("Close", Type.EmptyTypes).Invoke(port, null); } catch (Exception) { }
        }
    }

    public sealed class RiftAuthority : IDisposable
    {
        const string Capabilities = "fleet_management,monitoring";

        readonly RiftConfig cfg;
        readonly HttpClient http = new HttpClient { Timeout = TimeSpan.FromSeconds(2) };
        readonly object gate = new object();
        string mode = "wifi";
        string btPort = "";
        CancellationTokenSource cts;
        Task task;

        public RiftAuthority(RiftConfig cfg) { this.cfg = cfg; }

        public KeyValuePair<string, string> State
        {
            get { lock (gate) return new KeyValuePair<string, string>(mode, btPort); }
        }

        // Retires the current heartbeat (if any) and starts one on the given transport.
        public void Restart(string newMode, string newBtPort)
        {
            lock (gate)
            {
                StopLocked();
                mode = newMode;
                btPort = newBtPort;
                if (cfg.NoHeartbeat) return;
                cts = new CancellationTokenSource();
                var token = cts.Token;
                task = Task.Run(() => Loop(newMode, newBtPort, token));
            }
        }

        void StopLocked()
        {
            if (cts == null) return;
            cts.Cancel();
            try { task.Wait(TimeSpan.FromSeconds(2)); } catch (Exception) { }
            cts = null;
            task = null;
        }

        async Task AnnounceWifi()
        {
            try
            {
                var form = new FormUrlEncodedContent(new[]
                {
                    new KeyValuePair<string, string>("name", cfg.Name),
                    new KeyValuePair<string, string>("type", "fleet_manager"),
                    new KeyValuePair<string, string>("capabilities", Capabilities),
                });
                using (await http.PostAsync("http://" + cfg.NoraHost + ":" + cfg.NoraPort + "/register", form)) { }
            }
            catch (Exception)
            {
                // NORA may not be reachable yet (booting, or not on her AP) - keep retrying.
            }
        }

        async Task Loop(string loopMode, string loopBtPort, CancellationToken ct)
        {
            SerialLink bt = null;
            try
            {
                while (!ct.IsCancellationRequested)
                {
                    if (loopMode == "bluetooth")
                    {
                        try
                        {
                            if (bt == null) bt = new SerialLink(loopBtPort, 115200);
                            bt.Register(cfg.Name, Capabilities);
                        }
                        catch (Exception)
                        {
                            bt?.Dispose();
                            bt = null; // drop the link and reopen next round
                        }
                    }
                    else await AnnounceWifi();

                    try { await Task.Delay(TimeSpan.FromSeconds(cfg.HeartbeatSecs), ct); }
                    catch (OperationCanceledException) { }
                }
            }
            finally { bt?.Dispose(); }
        }

        public void Dispose()
        {
            lock (gate) StopLocked();
            http.Dispose();
        }
    }
}
