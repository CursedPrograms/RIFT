using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Net.Http;
using System.Text;
using System.Threading.Tasks;
using UnityEngine;
using UnityEngine.Networking;
using Rift;

// RIFT fleet hub inside Unity: the same fleet registry, dashboard, mDNS discovery,
// NORA fleet-authority heartbeat (WiFi or Bluetooth) and internet share as app.py,
// served on port 5000 with the same protocol, so run this OR app.py, not both.
// The hub itself lives in Assets/Rift (plain C#, no UnityEngine dependency).
//
// It starts by itself when the game runs (see Bootstrap) - no scene setup needed -
// and shows the live fleet: a card per robot with its page and a STOP button,
// the zeroconf peers, the log, and the hub's settings (kept between runs).
// In the editor it serves the repo's templates/ and static/; a built app serves the
// copy Editor/BuildRift.cs packs into StreamingAssets (unpacked first on Android).
// Bluetooth mode needs Edit > Project Settings > Player > Api Compatibility Level =
// ".NET Framework" (System.IO.Ports isn't in the default .NET Standard 2.1 profile).
public class main : MonoBehaviour
{
    [Header("Fleet hub (the settings panel overrides these once saved)")]
    public string hubName = "RIFT";
    public int port = 5000;
    public string noraHost = "192.168.4.1";
    public int noraPort = 5000;
    [Tooltip("Heartbeat to NORA so she defers her /robots registry to this hub.")]
    public bool announceToNora = true;
    public bool useMdns = true;
    [Tooltip("Linux + NetworkManager only: join NORA's WiFi AP and share internet to it.")]
    public bool shareInternet = true;

    // Each robot's own page, when it doesn't say (web:<port>): RIFT's README port table
    static readonly Dictionary<string, int> KnownPorts = new Dictionary<string, int>
    {
        { "DREAM", 5001 }, { "NORA", 5002 }, { "KIDA00", 5003 }, { "KIDA-00", 5003 }, { "KIDA01", 5004 },
        { "KIDA-01", 5004 }, { "WHIP", 5005 }, { "MILA", 5010 }, { "ARM", 5011 }, { "NINA", 5012 }, { "TINA", 5013 },
    };
    static readonly HttpClient Http = new HttpClient { Timeout = TimeSpan.FromSeconds(4) };

    RiftHub hub;
    string startError;
    string root;
    string btPort = "";
    readonly List<string> logLines = new List<string>();
    readonly object logLock = new object();
    List<Robot> robots = new List<Robot>();
    List<KeyValuePair<string, string>> peers = new List<KeyValuePair<string, string>>();
    readonly Dictionary<string, string> robotNote = new Dictionary<string, string>();   // "stop sent" etc., per robot
    float nextRefresh;
    Vector2 scroll;
    bool showSettings;
    string editName, editPort, editNoraHost;
    Texture2D avatar;

    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
    static void Bootstrap()
    {
        if (FindFirstObjectByType<main>() == null)
            new GameObject("RIFT Hub").AddComponent<main>();
    }

    void Log(string line)
    {
        Debug.Log(line);
        lock (logLock)
        {
            logLines.Add(DateTime.Now.ToString("HH:mm:ss ") + line);
            if (logLines.Count > 60) logLines.RemoveAt(0);
        }
    }

    // ---- settings, kept between runs ----
    void LoadSettings()
    {
        hubName = PlayerPrefs.GetString("rift.name", hubName);
        port = PlayerPrefs.GetInt("rift.port", port);
        noraHost = PlayerPrefs.GetString("rift.noraHost", noraHost);
        announceToNora = PlayerPrefs.GetInt("rift.nora", announceToNora ? 1 : 0) == 1;
        useMdns = PlayerPrefs.GetInt("rift.mdns", useMdns ? 1 : 0) == 1;
        shareInternet = PlayerPrefs.GetInt("rift.share", shareInternet ? 1 : 0) == 1;
    }

    void SaveSettings()
    {
        PlayerPrefs.SetString("rift.name", hubName);
        PlayerPrefs.SetInt("rift.port", port);
        PlayerPrefs.SetString("rift.noraHost", noraHost);
        PlayerPrefs.SetInt("rift.nora", announceToNora ? 1 : 0);
        PlayerPrefs.SetInt("rift.mdns", useMdns ? 1 : 0);
        PlayerPrefs.SetInt("rift.share", shareInternet ? 1 : 0);
        PlayerPrefs.Save();
    }

    IEnumerator Start()
    {
        Application.runInBackground = true; // keep serving when the window loses focus
        LoadSettings();
        yield return FindFiles();
        LoadAvatar();
        StartHub();
    }

    // Where templates/ and static/ are: the repo in the editor ("Unity App/RIFT/Assets" is three
    // levels down), the packed copy in a desktop build, unpacked to persistentDataPath on Android.
    IEnumerator FindFiles()
    {
        var packed = Path.Combine(Application.streamingAssetsPath, "rift");
        if (Application.platform == RuntimePlatform.Android)
        {
            var dest = Path.Combine(Application.persistentDataPath, "rift");
            var list = UnityWebRequest.Get(packed + "/files.txt");
            yield return list.SendWebRequest();
            if (list.result == UnityWebRequest.Result.Success)
            {
                foreach (var rel in list.downloadHandler.text.Split('\n').Select(l => l.Trim()).Where(l => l.Length > 0))
                {
                    var req = UnityWebRequest.Get(packed + "/" + rel);
                    yield return req.SendWebRequest();
                    if (req.result != UnityWebRequest.Result.Success) continue;
                    var to = Path.Combine(dest, rel);
                    Directory.CreateDirectory(Path.GetDirectoryName(to));
                    File.WriteAllBytes(to, req.downloadHandler.data);
                }
            }
            packed = dest;
        }
        root = RiftConfig.FindRoot(Application.dataPath, packed, Directory.GetCurrentDirectory());
    }

    void StartHub()
    {
        hub?.Dispose();
        var cfg = new RiftConfig
        {
            Name = hubName,
            Port = port,
            NoraHost = noraHost,
            NoraPort = noraPort,
            NoHeartbeat = !announceToNora,
            NoMdns = !useMdns,
            NoInternetShare = !shareInternet,
            Ip = RiftConfig.LocalIp(),
            Root = root,
        };
        hub = new RiftHub(cfg, Log);
        startError = hub.Start();
        if (startError != null) Debug.LogError("[RIFT] " + startError);
        else Log("Server started at " + DashboardUrl);
        styles = null;   // colours come from the hub's root: build them again
    }

    string DashboardUrl => hub == null ? "" : "http://" + hub.Config.Ip + ":" + hub.Config.Port + "/";

    void Update()
    {
        if (hub == null || Time.unscaledTime < nextRefresh) return;
        nextRefresh = Time.unscaledTime + 0.5f;
        robots = hub.Registry.Robots();
        peers = hub.Peers.Snapshot();
    }

    // ---- a robot's own page and its STOP ----
    static int RobotPort(Robot r)
    {
        foreach (var cap in r.Capabilities)
            if (cap.StartsWith("web:") && int.TryParse(cap.Substring(4), out var p)) return p;
        return KnownPorts.TryGetValue(r.Name.ToUpperInvariant(), out var known) ? known : 0;
    }

    void SendStop(Robot r)
    {
        var url = "http://" + r.Ip + ":" + RobotPort(r) + "/do";
        lock (robotNote) robotNote[r.Name] = "stopping...";
        Task.Run(async () =>
        {
            string note;
            try
            {
                var body = new StringContent("{\"action\": \"stop\"}", Encoding.UTF8, "application/json");
                var resp = await Http.PostAsync(url, body);
                note = resp.IsSuccessStatusCode ? "stop sent" : "stop: HTTP " + (int)resp.StatusCode;
            }
            catch (Exception e) { note = "stop failed: " + e.GetBaseException().Message; }
            lock (robotNote) robotNote[r.Name] = note;
            Log(r.Name + ": " + note);
        });
    }

    // ---- colour scheme ----
    // Colours come from colour_scheme.xml (the repo's, or the packed copy), the same file the
    // fleet dashboard uses. A missing file or role keeps the default below.
    readonly Dictionary<string, Color> scheme = new Dictionary<string, Color>
    {
        { "background", Hex("#0A0B07") }, { "panel", Hex("#14160F") }, { "border", Hex("#2A2E1F") },
        { "text", Hex("#F1F5E6") }, { "text_sec", Hex("#9DA38C") }, { "text_dim", Hex("#5E6352") },
        { "accent", Hex("#A3E635") }, { "accent_hover", Hex("#BEF264") }, { "button_hover_bg", Hex("#1C2112") },
        { "danger", Hex("#EF4444") },
    };
    class Styles { public GUIStyle box, card, title, head, label, dim, button, danger, field, toggle; public Texture2D bg; }
    Styles styles;

    static Color Hex(string hex) { ColorUtility.TryParseHtmlString(hex, out var c); return c; }

    static Texture2D Solid(Color c)
    {
        var t = new Texture2D(1, 1) { hideFlags = HideFlags.HideAndDontSave };
        t.SetPixel(0, 0, c);
        t.Apply();
        return t;
    }

    void LoadScheme()
    {
        var path = string.IsNullOrEmpty(root) ? null : Path.Combine(root, "colour_scheme.xml");
        if (path == null || !File.Exists(path)) return;
        try
        {
            foreach (System.Text.RegularExpressions.Match m in System.Text.RegularExpressions.Regex.Matches(
                         File.ReadAllText(path), "name=\"(\\w+)\"\\s+value=\"(#[0-9A-Fa-f]{6})\""))
                scheme[m.Groups[1].Value] = Hex(m.Groups[2].Value);
        }
        catch (IOException) { }
    }

    void LoadAvatar()
    {
        foreach (var name in new[] { "avatar_round.png", "rift_avatar.png", "rift_avatar.jpg" })
        {
            var path = string.IsNullOrEmpty(root) ? null : Path.Combine(root, "images", name);
            if (path == null || !File.Exists(path)) continue;
            var t = new Texture2D(2, 2);
            if (t.LoadImage(File.ReadAllBytes(path))) { avatar = t; return; }
        }
    }

    Styles BuildStyles()
    {
        LoadScheme();
        var s = new Styles { bg = Solid(scheme["background"]) };
        int fs = Mathf.Clamp(Screen.height / 50, 13, 22);   // readable on a phone and a big monitor

        s.box = new GUIStyle(GUI.skin.box) { padding = new RectOffset(16, 16, 14, 14) };
        s.box.normal.background = Solid(scheme["panel"]);
        s.card = new GUIStyle(s.box) { padding = new RectOffset(12, 12, 10, 10), margin = new RectOffset(0, 0, 4, 4) };
        s.card.normal.background = Solid(scheme["background"]);

        s.label = new GUIStyle(GUI.skin.label) { fontSize = fs, wordWrap = true };
        s.label.normal.textColor = scheme["text"];
        s.dim = new GUIStyle(s.label) { fontSize = fs - 2 };
        s.dim.normal.textColor = scheme["text_sec"];
        s.head = new GUIStyle(s.label) { fontStyle = FontStyle.Bold, fontSize = fs + 1 };
        s.head.normal.textColor = scheme["accent"];
        s.title = new GUIStyle(s.head) { fontSize = fs + 8 };

        s.button = new GUIStyle(GUI.skin.button) { fontSize = fs, padding = new RectOffset(12, 12, 6, 6) };
        s.button.normal.background = Solid(scheme["border"]);
        s.button.normal.textColor = scheme["accent"];
        s.button.hover.background = s.button.active.background = Solid(scheme["button_hover_bg"]);
        s.button.hover.textColor = s.button.active.textColor = scheme["accent_hover"];
        s.danger = new GUIStyle(s.button);
        s.danger.normal.textColor = s.danger.hover.textColor = s.danger.active.textColor = scheme["danger"];

        s.field = new GUIStyle(GUI.skin.textField) { fontSize = fs };
        s.field.normal.background = s.field.focused.background = Solid(scheme["background"]);
        s.field.normal.textColor = s.field.focused.textColor = scheme["text"];
        s.toggle = new GUIStyle(GUI.skin.toggle) { fontSize = fs };
        s.toggle.normal.textColor = s.toggle.onNormal.textColor = scheme["text"];
        return s;
    }

    void OnGUI()
    {
        if (styles == null) styles = BuildStyles();
        var s = styles;
        GUI.DrawTexture(new Rect(0, 0, Screen.width, Screen.height), s.bg);

        float pad = 12, w = Screen.width - 2 * pad;
        GUILayout.BeginArea(new Rect(pad, pad, w, Screen.height - 2 * pad), s.box);

        // header: avatar, name, address, the dashboard
        GUILayout.BeginHorizontal();
        if (avatar != null) GUILayout.Label(avatar, GUILayout.Width(s.title.fontSize * 3), GUILayout.Height(s.title.fontSize * 3));
        GUILayout.BeginVertical();
        GUILayout.Label("RIFT", s.title);
        GUILayout.Label("Real-time Intelligent Fleet Technology", s.dim);
        if (hub != null && startError == null) GUILayout.Label(hub.Config.Name + " at " + DashboardUrl, s.label);
        GUILayout.EndVertical();
        GUILayout.FlexibleSpace();
        if (hub != null && startError == null && GUILayout.Button("Dashboard", s.button)) Application.OpenURL(DashboardUrl);
        if (GUILayout.Button(showSettings ? "Close settings" : "Settings", s.button)) ToggleSettings();
        GUILayout.EndHorizontal();

        if (showSettings) { DrawSettings(s); GUILayout.EndArea(); return; }
        if (hub == null) { GUILayout.Label("Starting...", s.dim); GUILayout.EndArea(); return; }
        if (startError != null)
        {
            GUILayout.Label("Could not start: " + startError, s.label);
            GUILayout.Label("Another hub (app.py?) may already use port " + port + ": change it in Settings.", s.dim);
            GUILayout.EndArea();
            return;
        }

        var state = hub.Authority.State;
        GUILayout.BeginHorizontal();
        GUILayout.Label("NORA link: " + state.Key, s.label, GUILayout.ExpandWidth(false));
        GUILayout.Space(12);
        if (GUILayout.Button("WiFi", s.button, GUILayout.ExpandWidth(false))) hub.Authority.Restart("wifi", "");
        btPort = GUILayout.TextField(btPort, s.field, GUILayout.Width(w * 0.25f));
        if (GUILayout.Button("Bluetooth", s.button, GUILayout.ExpandWidth(false)) && btPort.Trim().Length > 0)
            hub.Authority.Restart("bluetooth", btPort.Trim());
        GUILayout.FlexibleSpace();
        GUILayout.EndHorizontal();

        scroll = GUILayout.BeginScrollView(scroll);
        GUILayout.Label("Fleet (" + robots.Count + ")", s.head);
        if (robots.Count == 0) GUILayout.Label("Nobody has registered yet. Robots heartbeat every 10 s.", s.dim);
        int perRow = Mathf.Max(1, Mathf.FloorToInt(w / 360f));
        for (int i = 0; i < robots.Count; i += perRow)
        {
            GUILayout.BeginHorizontal();
            foreach (var r in robots.Skip(i).Take(perRow)) DrawRobot(s, r, (w - 40) / perRow);
            GUILayout.EndHorizontal();
        }

        GUILayout.Space(8);
        GUILayout.Label("Other hubs on the network (" + peers.Count + ")", s.head);
        foreach (var p in peers) GUILayout.Label(p.Key + "  -  " + p.Value, s.dim);

        GUILayout.Space(8);
        GUILayout.Label("Log", s.head);
        string[] lines;
        lock (logLock) lines = logLines.ToArray();
        foreach (var line in lines.Reverse().Take(15)) GUILayout.Label(line, s.dim);
        GUILayout.EndScrollView();
        GUILayout.EndArea();
    }

    void DrawRobot(Styles s, Robot r, float width)
    {
        GUILayout.BeginVertical(s.card, GUILayout.Width(width));
        GUILayout.Label(r.Name, s.head);
        GUILayout.Label(r.Type + "  @ " + r.Ip, s.label);
        GUILayout.Label(r.Capabilities.Count > 0 ? string.Join(", ", r.Capabilities) : "no capabilities", s.dim);
        GUILayout.BeginHorizontal();
        int robotPort = RobotPort(r);
        if (robotPort > 0 && GUILayout.Button("Page", s.button)) Application.OpenURL("http://" + r.Ip + ":" + robotPort + "/");
        if (r.Capabilities.Contains("do:stop") && robotPort > 0 && GUILayout.Button("STOP", s.danger)) SendStop(r);
        GUILayout.FlexibleSpace();
        GUILayout.EndHorizontal();
        string note;
        lock (robotNote) robotNote.TryGetValue(r.Name, out note);
        if (!string.IsNullOrEmpty(note)) GUILayout.Label(note, s.dim);
        GUILayout.EndVertical();
    }

    void ToggleSettings()
    {
        showSettings = !showSettings;
        if (showSettings) { editName = hubName; editPort = port.ToString(); editNoraHost = noraHost; }
    }

    void DrawSettings(Styles s)
    {
        GUILayout.Space(8);
        GUILayout.Label("Hub settings", s.head);
        GUILayout.Label("Name", s.dim);
        editName = GUILayout.TextField(editName, s.field);
        GUILayout.Label("Port (5000 is the fleet's; robots register there)", s.dim);
        editPort = GUILayout.TextField(editPort, s.field);
        GUILayout.Label("NORA's address", s.dim);
        editNoraHost = GUILayout.TextField(editNoraHost, s.field);
        announceToNora = GUILayout.Toggle(announceToNora, " Heartbeat to NORA (she defers her fleet list to this hub)", s.toggle);
        useMdns = GUILayout.Toggle(useMdns, " Find other hubs over mDNS / zeroconf", s.toggle);
        shareInternet = GUILayout.Toggle(shareInternet, " Share internet to NORA's network (Linux + NetworkManager)", s.toggle);
        GUILayout.Space(8);
        GUILayout.BeginHorizontal();
        if (GUILayout.Button("Save and restart the hub", s.button, GUILayout.ExpandWidth(false)))
        {
            hubName = string.IsNullOrWhiteSpace(editName) ? "RIFT" : editName.Trim();
            if (int.TryParse(editPort, out var p) && p > 0 && p < 65536) port = p;
            noraHost = string.IsNullOrWhiteSpace(editNoraHost) ? noraHost : editNoraHost.Trim();
            SaveSettings();
            StartHub();
            showSettings = false;
        }
        if (GUILayout.Button("Cancel", s.button, GUILayout.ExpandWidth(false))) { LoadSettings(); showSettings = false; }
        GUILayout.EndHorizontal();
    }

    void OnDestroy() { hub?.Dispose(); hub = null; }
    void OnApplicationQuit() { hub?.Dispose(); hub = null; }
}
