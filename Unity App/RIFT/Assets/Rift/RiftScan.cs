// RiftScan.cs - the subnet-scanning client (C# counterpart of
// PC App/App/registration.cpp and PC App/PyGame/registration.py): queries every
// host on this machine's /24 for :<port>/robots and reports whatever answers.

using System;
using System.Collections.Generic;
using System.Linq;
using System.Net.Http;
using System.Threading;
using System.Threading.Tasks;

namespace Rift
{
    public static class RiftScan
    {
        // Both RIFT and NORA serve {"authority": "...", "robots": [...]}, not a bare array.
        static async Task<List<Robot>> QueryHost(HttpClient http, string ip, int port)
        {
            var found = new List<Robot>();
            try
            {
                var body = await http.GetStringAsync("http://" + ip + ":" + port + "/robots");
                if (!(MiniJson.Parse(body) is Dictionary<string, object> root) || !(root.TryGetValue("robots", out var list) && list is List<object> robots))
                    return found;
                foreach (var item in robots.OfType<Dictionary<string, object>>())
                {
                    var robot = new Robot
                    {
                        Name = item.TryGetValue("name", out var n) ? n as string ?? "" : "",
                        Type = item.TryGetValue("type", out var t) ? t as string ?? "" : "",
                        Ip = ip,
                    };
                    if (item.TryGetValue("capabilities", out var c) && c is List<object> caps)
                        robot.Capabilities = caps.OfType<string>().ToList();
                    found.Add(robot);
                }
            }
            catch (Exception)
            {
                // nothing listening there, or not a RIFT/NORA hub
            }
            return found;
        }

        // Scans <base>.1-254 and returns everything found.
        public static List<Robot> Run(string localIp, int port)
        {
            string baseIp = localIp.Substring(0, localIp.LastIndexOf('.')); // assumes a /24
            using (var http = new HttpClient { Timeout = TimeSpan.FromMilliseconds(500) })
            using (var gate = new SemaphoreSlim(50))
            {
                var tasks = Enumerable.Range(1, 254).Select(async i =>
                {
                    await gate.WaitAsync();
                    try { return await QueryHost(http, baseIp + "." + i, port); }
                    finally { gate.Release(); }
                }).ToArray();
                Task.WaitAll(tasks);
                return tasks.SelectMany(t => t.Result).ToList();
            }
        }
    }
}
