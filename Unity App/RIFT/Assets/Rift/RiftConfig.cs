// RiftConfig.cs - hub configuration and repo-root discovery.
//
// Everything under Assets/Rift is plain C# with no UnityEngine dependency (and
// only C# 9 / .NET Standard 2.1 APIs), so the hub can run inside Unity or be
// unit-tested from a normal .NET console project.

using System;
using System.IO;
using System.Net;
using System.Net.Sockets;

namespace Rift
{
    public sealed class RiftConfig
    {
        public string Name = "RIFT";
        public int Port = 5000;
        public string Ip = "127.0.0.1";
        public string Root = "";
        public double TtlSecs = 20;
        public string NoraHost = "192.168.4.1";
        public int NoraPort = 5000;
        public double HeartbeatSecs = 10;
        public bool NoHeartbeat;
        public bool NoMdns;
        public bool NoInternetShare;

        // Same trick as app.py's _get_ip(): "connect" a UDP socket (no traffic is
        // sent) and read back which local address the OS would use.
        public static string LocalIp()
        {
            foreach (var target in new[] { "10.255.255.255", "8.8.8.8" })
            {
                try
                {
                    using (var s = new Socket(AddressFamily.InterNetwork, SocketType.Dgram, ProtocolType.Udp))
                    {
                        s.Connect(IPAddress.Parse(target), 1);
                        return ((IPEndPoint)s.LocalEndPoint).Address.ToString();
                    }
                }
                catch (SocketException)
                {
                }
            }
            return "127.0.0.1";
        }

        // Walks up from each start directory until it finds the RIFT repo root
        // (app.py next to templates/). Inside the Unity project that's
        // "Unity App/RIFT/Assets" -> three levels up.
        public static string FindRoot(params string[] starts)
        {
            foreach (var start in starts)
            {
                if (string.IsNullOrEmpty(start)) continue;
                for (var dir = new DirectoryInfo(start); dir != null; dir = dir.Parent)
                {
                    if (File.Exists(Path.Combine(dir.FullName, "app.py")) &&
                        File.Exists(Path.Combine(dir.FullName, "templates", "index.html")))
                        return dir.FullName;
                }
            }
            return Directory.GetCurrentDirectory();
        }

        public const string Usage =
            "usage: rift [--name RIFT] [--port 5000] [--nora-host 192.168.4.1] [--nora-port 5000]\n" +
            "            [--heartbeat-secs 10] [--ttl-secs 20] [--no-heartbeat] [--no-mdns]\n" +
            "            [--no-internet-share] [--root <repo>] [--scan]";

        // Returns null on success, else an error/usage message.
        public static string Parse(string[] args, RiftConfig cfg, out bool scan)
        {
            scan = false;
            string root = "";
            for (int i = 0; i < args.Length; i++)
            {
                string flag = args[i].TrimStart('-');
                string Next() => i + 1 < args.Length ? args[++i] : null;
                string v;
                switch (flag)
                {
                    case "scan": scan = true; break;
                    case "no-mdns": cfg.NoMdns = true; break;
                    case "no-heartbeat": cfg.NoHeartbeat = true; break;
                    case "no-internet-share": cfg.NoInternetShare = true; break;
                    case "help":
                    case "h": return Usage;
                    case "name": if ((v = Next()) == null) return "--name requires a value"; cfg.Name = v; break;
                    case "nora-host": if ((v = Next()) == null) return "--nora-host requires a value"; cfg.NoraHost = v; break;
                    case "root": if ((v = Next()) == null) return "--root requires a value"; root = v; break;
                    case "port":
                        if (!int.TryParse(Next(), out cfg.Port)) return "--port requires a number";
                        break;
                    case "nora-port":
                        if (!int.TryParse(Next(), out cfg.NoraPort)) return "--nora-port requires a number";
                        break;
                    case "heartbeat-secs":
                        if (!double.TryParse(Next(), System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out cfg.HeartbeatSecs))
                            return "--heartbeat-secs requires a number";
                        break;
                    case "ttl-secs":
                        if (!double.TryParse(Next(), System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out cfg.TtlSecs))
                            return "--ttl-secs requires a number";
                        break;
                    default: return "unknown argument: " + args[i] + "\n" + Usage;
                }
            }
            cfg.Ip = LocalIp();
            cfg.Root = root.Length > 0 ? root : FindRoot(AppContext.BaseDirectory, Directory.GetCurrentDirectory());
            return null;
        }
    }
}
