// RiftHub.cs - the fleet hub: HTTP registry + dashboard on top of the registry,
// mDNS peers, NORA authority and internet share. Same wire protocol as app.py's
// Flask routes (and NORA's fleet server), so PC App/PyGame/registration.py,
// PC App/App/registration.cpp and every robot's heartbeat work unchanged.

using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.RegularExpressions;

namespace Rift
{
    public sealed class RiftHub : IDisposable
    {
        public readonly RiftConfig Config;
        public readonly RiftRegistry Registry;
        public readonly RiftPeers Peers = new RiftPeers();
        public readonly RiftAuthority Authority;

        readonly Action<string> log;
        RiftHttpServer server;
        RiftMdns mdns;
        RiftShare share;

        public RiftHub(RiftConfig config, Action<string> log = null)
        {
            Config = config;
            Registry = new RiftRegistry(config.TtlSecs);
            Authority = new RiftAuthority(config);
            this.log = log ?? (_ => { });
        }

        // Starts everything. Returns null on success, else an error message (e.g. port in use).
        public string Start()
        {
            log("[RIFT] IP   : " + Config.Ip + "\n[RIFT] Port : " + Config.Port + "\n[RIFT] Root : " + Config.Root);

            if (!Config.NoMdns)
            {
                mdns = new RiftMdns(Config, Peers);
                var err = mdns.Start();
                if (err == null) log("[RIFT] Zeroconf registered as " + Config.Name + "; watching _rift._tcp and _flask-link._tcp");
                else { log("[RIFT] Continuing without mDNS: " + err); mdns = null; }
            }

            Authority.Restart("wifi", "");
            log(Config.NoHeartbeat
                ? "[RIFT] Not announcing to NORA (--no-heartbeat)"
                : "[RIFT] Announcing to NORA at " + Config.NoraHost + ":" + Config.NoraPort + " as fleet authority (mode: wifi)");

            if (!Config.NoInternetShare)
            {
                share = new RiftShare();
                share.Start();
            }

            server = new RiftHttpServer(Config.Port, Handle);
            var serverError = server.Start();
            if (serverError != null) { Dispose(); return serverError; }
            return null;
        }

        public void Dispose()
        {
            server?.Dispose();
            share?.Dispose();
            Authority.Dispose();
            mdns?.Dispose();
            server = null; share = null; mdns = null;
        }

        // ---- HTTP routes ----

        static readonly Regex TemplateTag = new Regex(@"\{\{\s*(.*?)\s*\}\}");
        static readonly Regex UrlForStatic = new Regex(@"^url_for\(\s*'static'\s*,\s*filename\s*=\s*'([^']*)'\s*\)$");

        // Fills in the handful of Jinja expressions templates/index.html uses:
        // {{ this_name }}, {{ my_ip }}, {{ this_port }} and url_for('static', filename=...).
        public static string RenderTemplate(string tpl, Dictionary<string, string> vars)
        {
            return TemplateTag.Replace(tpl, m =>
            {
                string expr = m.Groups[1].Value;
                if (vars.TryGetValue(expr, out var v)) return v;
                var u = UrlForStatic.Match(expr);
                return u.Success ? "/static/" + u.Groups[1].Value : m.Value;
            });
        }

        static string ContentTypeFor(string path)
        {
            switch (Path.GetExtension(path).ToLowerInvariant())
            {
                case ".css": return "text/css; charset=utf-8";
                case ".js": return "application/javascript; charset=utf-8";
                case ".html": return "text/html; charset=utf-8";
                case ".json": return "application/json";
                case ".svg": return "image/svg+xml";
                case ".png": return "image/png";
                case ".ico": return "image/x-icon";
                default: return "application/octet-stream";
            }
        }

        static HttpReply Json(int status, string body) => HttpReply.Text(status, "application/json", body);

        static Dictionary<string, string> ParseForm(string body)
        {
            var form = new Dictionary<string, string>();
            foreach (var pair in body.Split(new[] { '&' }, StringSplitOptions.RemoveEmptyEntries))
            {
                int eq = pair.IndexOf('=');
                string k = Uri.UnescapeDataString((eq < 0 ? pair : pair.Substring(0, eq)).Replace('+', ' '));
                string v = eq < 0 ? "" : Uri.UnescapeDataString(pair.Substring(eq + 1).Replace('+', ' '));
                form[k] = v;
            }
            return form;
        }

        // app.py reads a form body; the Android app's Registration.kt sends JSON, so
        // both are accepted. Arrays (e.g. "capabilities") are joined back into a CSV.
        static Dictionary<string, string> ReadFields(HttpRequestInfo req)
        {
            if (!req.Header("Content-Type").StartsWith("application/json", StringComparison.OrdinalIgnoreCase))
                return ParseForm(req.Body);
            var fields = new Dictionary<string, string>();
            try
            {
                if (MiniJson.Parse(req.Body) is Dictionary<string, object> obj)
                    foreach (var kv in obj)
                    {
                        if (kv.Value is string s) fields[kv.Key] = s;
                        else if (kv.Value is List<object> list) fields[kv.Key] = string.Join(",", list.OfType<string>());
                    }
            }
            catch (FormatException) { }
            return fields;
        }

        static string Field(Dictionary<string, string> f, string key) => f.TryGetValue(key, out var v) ? v : "";

        static string RobotJson(Robot r) =>
            MiniJson.Obj(MiniJson.F("name", MiniJson.Str(r.Name)), MiniJson.F("ip", MiniJson.Str(r.Ip)),
                         MiniJson.F("type", MiniJson.Str(r.Type)),
                         MiniJson.F("capabilities", MiniJson.Arr(r.Capabilities.Select(MiniJson.Str))));

        HttpReply HandleRegister(HttpRequestInfo req)
        {
            var f = ReadFields(req);
            string name = Field(f, "name");
            if (name.Length == 0) return HttpReply.Text(400, "text/plain", "missing name");
            string type = Field(f, "type"), ip = Field(f, "ip");
            Registry.Add(name, ip.Length > 0 ? ip : req.RemoteIp, type.Length > 0 ? type : "unknown",
                         Field(f, "capabilities").Split(new[] { ',' }, StringSplitOptions.RemoveEmptyEntries).ToList());
            return HttpReply.Text(200, "text/plain", "OK");
        }

        HttpReply HandleSetMode(HttpRequestInfo req)
        {
            var f = ReadFields(req);
            string mode = Field(f, "mode").Trim().ToLowerInvariant(), btPort = Field(f, "bt_port").Trim();
            if (mode != "wifi" && mode != "bluetooth")
                return Json(400, MiniJson.Obj(MiniJson.F("error", MiniJson.Str("mode must be 'wifi' or 'bluetooth'"))));
            if (mode == "bluetooth" && btPort.Length == 0)
                return Json(400, MiniJson.Obj(MiniJson.F("error", MiniJson.Str("bt_port is required for Bluetooth mode"))));
            Authority.Restart(mode, btPort);
            return Json(200, MiniJson.Obj(MiniJson.F("mode", MiniJson.Str(mode)), MiniJson.F("bt_port", MiniJson.NullOrStr(btPort))));
        }

        HttpReply ServeStatic(string rawRel)
        {
            string rel = Uri.UnescapeDataString(rawRel);
            string staticDir = Path.GetFullPath(Path.Combine(Config.Root, "static"));
            string full = Path.GetFullPath(Path.Combine(staticDir, rel));
            if (rel.Length > 0 && full.StartsWith(staticDir + Path.DirectorySeparatorChar) && File.Exists(full))
                return new HttpReply { Status = 200, ContentType = ContentTypeFor(full), Body = File.ReadAllBytes(full) };
            return HttpReply.Text(404, "text/plain", "Not found");
        }

        public HttpReply Handle(HttpRequestInfo req)
        {
            string path = req.Path, method = req.Method;
            var known = new[] { "/ping", "/register", "/robots", "/peers", "/mode", "/" };

            if (method == "GET" && path == "/ping") return HttpReply.Text(200, "text/plain", Config.Name + " alive");
            if (method == "POST" && path == "/register") return HandleRegister(req);
            if (method == "GET" && path == "/robots")
                return Json(200, MiniJson.Obj(MiniJson.F("authority", MiniJson.Str(Config.Name)),
                                              MiniJson.F("robots", MiniJson.Arr(Registry.Robots().Select(RobotJson)))));
            if (method == "GET" && path == "/peers")
                return Json(200, MiniJson.Obj(Peers.Snapshot().Select(kv => MiniJson.F(kv.Key, MiniJson.Str(kv.Value))).ToArray()));
            if (method == "GET" && path == "/mode")
            {
                var st = Authority.State;
                return Json(200, MiniJson.Obj(MiniJson.F("mode", MiniJson.Str(st.Key)), MiniJson.F("bt_port", MiniJson.NullOrStr(st.Value))));
            }
            if (method == "POST" && path == "/mode") return HandleSetMode(req);
            if (method == "GET" && path == "/")
            {
                string file = Path.Combine(Config.Root, "templates", "index.html");
                if (!File.Exists(file)) return HttpReply.Text(500, "text/plain", "dashboard template not found");
                return HttpReply.Text(200, "text/html; charset=utf-8", RenderTemplate(File.ReadAllText(file), new Dictionary<string, string>
                {
                    ["this_name"] = Config.Name, ["my_ip"] = Config.Ip, ["this_port"] = Config.Port.ToString(),
                }));
            }
            if (method == "GET" && path.StartsWith("/static/")) return ServeStatic(path.Substring("/static/".Length));
            if (known.Contains(path)) return HttpReply.Text(405, "text/plain", "Method Not Allowed");
            return HttpReply.Text(404, "text/plain", "Not found");
        }
    }
}
