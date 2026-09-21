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

    void OnGUI()
    {
        GUILayout.BeginArea(new Rect(10, 10, Mathf.Min(Screen.width - 20, 640), Screen.height - 20), GUI.skin.box);
        GUILayout.Label("RIFT: Real-time Intelligent Fleet Technology");

        if (hub == null) { GUILayout.EndArea(); return; }
        if (startError != null)
        {
            GUILayout.Label("Could not start: " + startError);
            GUILayout.EndArea();
            return;
        }

        var cfg = hub.Config;
        GUILayout.Label(cfg.Name + "  -  http://" + cfg.Ip + ":" + cfg.Port + "/  (open it in a browser for the dashboard)");

        var state = hub.Authority.State;
        GUILayout.BeginHorizontal();
        GUILayout.Label("Connection mode: " + state.Key, GUILayout.Width(200));
        if (GUILayout.Button("WiFi", GUILayout.Width(80))) hub.Authority.Restart("wifi", "");
        btPort = GUILayout.TextField(btPort, GUILayout.Width(140));
        if (GUILayout.Button("Bluetooth", GUILayout.Width(90)) && btPort.Trim().Length > 0) hub.Authority.Restart("bluetooth", btPort.Trim());
        GUILayout.EndHorizontal();

        scroll = GUILayout.BeginScrollView(scroll);
        GUILayout.Label("Registered fleet (" + robots.Count + ")");
        foreach (var r in robots)
            GUILayout.Label("  " + r.Name + "  -  " + r.Type + " @ " + r.Ip + "  -  " + (r.Capabilities.Count > 0 ? string.Join(", ", r.Capabilities) : "no capabilities"));

        GUILayout.Label("Zeroconf peers (" + peers.Count + ")");
        foreach (var p in peers) GUILayout.Label("  " + p.Key + "  -  " + p.Value);

        GUILayout.Label("Log");
        string[] lines;
        lock (logLock) lines = logLines.ToArray();
        foreach (var line in lines.Reverse().Take(12)) GUILayout.Label("  " + line);
        GUILayout.EndScrollView();
        GUILayout.EndArea();
    }

    void OnDestroy() { hub?.Dispose(); hub = null; }
    void OnApplicationQuit() { hub?.Dispose(); hub = null; }
}
