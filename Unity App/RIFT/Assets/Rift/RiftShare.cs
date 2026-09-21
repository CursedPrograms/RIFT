// RiftShare.cs - shares this RIFT instance's existing internet connection out to
// every device that joins NORA's isolated WiFi AP. C# counterpart of
// Fleet/internet_share.py: join NORA's AP as a secondary connection over a spare
// WiFi radio, then let NetworkManager's "shared" method (its own DHCP server +
// NAT) hand internet access to NORA and anything else on her AP, while RIFT's
// own default route is left alone. Linux + NetworkManager only; anywhere else it
// quietly does nothing.

using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using System.Threading;

namespace Rift
{
    public sealed class RiftShare : IDisposable
    {
        const string Ssid = "NORA";
        const string Password = "12345678";

        volatile bool stop;
        Thread thread;

        // Runs nmcli, killing it if it hasn't finished within timeoutMs; null on failure.
        static string Nmcli(int timeoutMs, params string[] args)
        {
            try
            {
                var psi = new ProcessStartInfo("nmcli", string.Join(" ", args.Select(a => a.Contains(' ') ? "\"" + a + "\"" : a)))
                {
                    RedirectStandardOutput = true,
                    RedirectStandardError = true,
                    UseShellExecute = false,
                };
                using (var p = Process.Start(psi))
                {
                    if (p.WaitForExit(timeoutMs)) return p.StandardOutput.ReadToEnd();
                    try { p.Kill(); } catch (Exception) { }
                    return null;
                }
            }
            catch (Exception)
            {
                return null;
            }
        }

        static List<string> Lines(string s) =>
            (s ?? "").Split('\n').Select(l => l.Trim()).Where(l => l.Length > 0).ToList();

        static string WifiIface()
        {
            foreach (var l in Lines(Nmcli(20000, "-t", "-f", "DEVICE,TYPE", "device", "status")))
            {
                var parts = l.Split(':');
                if (parts.Length >= 2 && parts[1] == "wifi") return parts[0];
            }
            return null;
        }

        static List<string> Active() => Lines(Nmcli(20000, "-t", "-f", "NAME", "connection", "show", "--active"));

        // Joins NORA's AP (if not already) and marks it shared. Safe to call
        // repeatedly; a no-op once already connected and shared.
        static void Ensure()
        {
            string iface = WifiIface();
            if (iface == null || Active().Contains(Ssid)) return;
            var known = Nmcli(20000, "-t", "-f", "NAME", "connection", "show");
            if (known == null) return;
            if (!Lines(known).Contains(Ssid))
            {
                Nmcli(30000, "device", "wifi", "connect", Ssid, "password", Password, "ifname", iface);
                Nmcli(20000, "connection", "modify", Ssid, "ipv4.method", "shared");
            }
            else Nmcli(30000, "connection", "up", Ssid);
        }

        public void Start()
        {
            if (Environment.OSVersion.Platform != PlatformID.Unix || Nmcli(5000, "--version") == null) return;
            thread = new Thread(() =>
            {
                while (!stop)
                {
                    Ensure();
                    for (int i = 0; i < 150 && !stop; i++) Thread.Sleep(200); // ~30 s
                }
            }) { IsBackground = true, Name = "rift-internet-share" };
            thread.Start();
        }

        public void Dispose()
        {
            stop = true;
            thread?.Join(2000);
        }
    }
}
