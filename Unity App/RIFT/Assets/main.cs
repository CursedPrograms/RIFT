using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEngine;
using Rift;

// RIFT fleet hub inside Unity: the same fleet registry, dashboard, mDNS discovery,
// NORA fleet-authority heartbeat (WiFi or Bluetooth) and internet share as app.py,
// served on port 5000 with the same protocol, so run this OR app.py, not both.
// The hub itself lives in Assets/Rift (plain C#, no UnityEngine dependency).
//
// It starts by itself when the game runs (see Bootstrap) - no scene setup needed -
// and shows the live fleet in an on-screen panel. Bluetooth mode needs
// Edit > Project Settings > Player > Api Compatibility Level = ".NET Framework"
// (System.IO.Ports isn't in the default .NET Standard 2.1 profile).
public class main : MonoBehaviour
{
    [Header("Fleet hub")]
    public string hubName = "RIFT";
    public int port = 5000;
    public string noraHost = "192.168.4.1";
    public int noraPort = 5000;
    [Tooltip("Heartbeat to NORA so she defers her /robots registry to this hub.")]
    public bool announceToNora = true;
    public bool useMdns = true;
    [Tooltip("Linux + NetworkManager only: join NORA's WiFi AP and share internet to it.")]
    public bool shareInternet = true;

    RiftHub hub;
    string startError;
    string btPort = "";
    readonly List<string> logLines = new List<string>();
    readonly object logLock = new object();
    List<Robot> robots = new List<Robot>();
    List<KeyValuePair<string, string>> peers = new List<KeyValuePair<string, string>>();
    float nextRefresh;
    Vector2 scroll;

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
            logLines.Add(line);
            if (logLines.Count > 40) logLines.RemoveAt(0);
        }
    }

    void Start()
    {
        Application.runInBackground = true; // keep serving when the window loses focus

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
            // Application.dataPath is "Unity App/RIFT/Assets"; the repo root is three levels up.
            Root = RiftConfig.FindRoot(Application.dataPath, Directory.GetCurrentDirectory()),
        };

        hub = new RiftHub(cfg, Log);
        startError = hub.Start();
        if (startError != null) Debug.LogError("[RIFT] " + startError);
        else Log("Server started at http://" + cfg.Ip + ":" + cfg.Port + "/");
    }

    void Update()
    {
        if (hub == null || Time.unscaledTime < nextRefresh) return;
        nextRefresh = Time.unscaledTime + 0.5f;
        robots = hub.Registry.Robots();
        peers = hub.Peers.Snapshot();
    }

    // ---- colour scheme ----
    // Colours come from colour_scheme.xml in the repo root, the same file the
    // fleet dashboard uses. A missing file or role keeps the default below.
    readonly Dictionary<string, Color> scheme = new Dictionary<string, Color>
    {
        { "background", Hex("#0A0B07") }, { "panel", Hex("#14160F") }, { "border", Hex("#2A2E1F") },
        { "text", Hex("#F1F5E6") }, { "text_sec", Hex("#9DA38C") }, { "text_dim", Hex("#5E6352") },
        { "accent", Hex("#A3E635") }, { "accent_hover", Hex("#BEF264") }, { "button_hover_bg", Hex("#1C2112") },
    };
    GUIStyle boxStyle, titleStyle, headStyle, labelStyle, dimStyle, buttonStyle, fieldStyle;
    Texture2D bgTex;

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
        var root = hub != null ? hub.Config.Root : RiftConfig.FindRoot(Application.dataPath, Directory.GetCurrentDirectory());
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

    void BuildStyles()
    {
        LoadScheme();
        bgTex = Solid(scheme["background"]);

        boxStyle = new GUIStyle(GUI.skin.box) { padding = new RectOffset(14, 14, 12, 12) };
        boxStyle.normal.background = Solid(scheme["panel"]);

        labelStyle = new GUIStyle(GUI.skin.label);
        labelStyle.normal.textColor = scheme["text"];
        dimStyle = new GUIStyle(labelStyle);
        dimStyle.normal.textColor = scheme["text_sec"];
        headStyle = new GUIStyle(labelStyle) { fontStyle = FontStyle.Bold };
        headStyle.normal.textColor = scheme["accent"];
        titleStyle = new GUIStyle(headStyle) { fontSize = 16 };

        buttonStyle = new GUIStyle(GUI.skin.button);
        buttonStyle.normal.background = Solid(scheme["border"]);
        buttonStyle.normal.textColor = scheme["accent"];
        buttonStyle.hover.background = buttonStyle.active.background = Solid(scheme["button_hover_bg"]);
        buttonStyle.hover.textColor = buttonStyle.active.textColor = scheme["accent_hover"];

        fieldStyle = new GUIStyle(GUI.skin.textField);
        fieldStyle.normal.background = fieldStyle.focused.background = Solid(scheme["background"]);
        fieldStyle.normal.textColor = fieldStyle.focused.textColor = scheme["text"];
    }

    void OnGUI()
    {
        if (boxStyle == null) BuildStyles();
        GUI.DrawTexture(new Rect(0, 0, Screen.width, Screen.height), bgTex);

        GUILayout.BeginArea(new Rect(10, 10, Mathf.Min(Screen.width - 20, 640), Screen.height - 20), boxStyle);
        GUILayout.Label("RIFT: Real-time Intelligent Fleet Technology", titleStyle);

        if (hub == null) { GUILayout.EndArea(); return; }
        if (startError != null)
        {
            GUILayout.Label("Could not start: " + startError, labelStyle);
            GUILayout.EndArea();
            return;
        }

        var cfg = hub.Config;
        GUILayout.Label(cfg.Name + "  -  http://" + cfg.Ip + ":" + cfg.Port + "/  (open it in a browser for the dashboard)", dimStyle);

        var state = hub.Authority.State;
        GUILayout.BeginHorizontal();
        GUILayout.Label("Connection mode: " + state.Key, labelStyle, GUILayout.Width(200));
        if (GUILayout.Button("WiFi", buttonStyle, GUILayout.Width(80))) hub.Authority.Restart("wifi", "");
        btPort = GUILayout.TextField(btPort, fieldStyle, GUILayout.Width(140));
        if (GUILayout.Button("Bluetooth", buttonStyle, GUILayout.Width(90)) && btPort.Trim().Length > 0) hub.Authority.Restart("bluetooth", btPort.Trim());
        GUILayout.EndHorizontal();

        scroll = GUILayout.BeginScrollView(scroll);
        GUILayout.Label("Registered fleet (" + robots.Count + ")", headStyle);
        foreach (var r in robots)
            GUILayout.Label("  " + r.Name + "  -  " + r.Type + " @ " + r.Ip + "  -  " + (r.Capabilities.Count > 0 ? string.Join(", ", r.Capabilities) : "no capabilities"), labelStyle);

        GUILayout.Label("Zeroconf peers (" + peers.Count + ")", headStyle);
        foreach (var p in peers) GUILayout.Label("  " + p.Key + "  -  " + p.Value, labelStyle);

        GUILayout.Label("Log", headStyle);
        string[] lines;
        lock (logLock) lines = logLines.ToArray();
        foreach (var line in lines.Reverse().Take(12)) GUILayout.Label("  " + line, dimStyle);
        GUILayout.EndScrollView();
        GUILayout.EndArea();
    }

    void OnDestroy() { hub?.Dispose(); hub = null; }
    void OnApplicationQuit() { hub?.Dispose(); hub = null; }
}
