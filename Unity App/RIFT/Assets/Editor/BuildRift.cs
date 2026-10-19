using System;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.Build.Reporting;
using UnityEngine;

// One-click builds of the RIFT hub app: RIFT > Build Windows / Build Android in the menu, or from a
// command line (build_unity.bat / build_unity.sh in the repo root):
//   Unity.exe -batchmode -quit -projectPath "Unity App/RIFT" -executeMethod BuildRift.Windows
//
// A built app doesn't live inside the repo, so first it packs what the hub serves - templates/,
// static/, colour_scheme.xml and RIFT's avatar - into Assets/StreamingAssets/rift (rebuilt every
// time; git ignores it). main.cs finds it there. Builds land in "Unity App/RIFT/Builds".
public static class BuildRift
{
    static string ProjectDir => Path.GetDirectoryName(Application.dataPath);
    static string RepoRoot => Path.GetFullPath(Path.Combine(ProjectDir, "..", ".."));
    static string Pack => Path.Combine(Application.dataPath, "StreamingAssets", "rift");

    [MenuItem("RIFT/Pack the dashboard files")]
    public static void PackFiles()
    {
        if (!File.Exists(Path.Combine(RepoRoot, "templates", "index.html")))
            throw new Exception("RIFT's templates/index.html not found at " + RepoRoot);
        if (Directory.Exists(Pack)) Directory.Delete(Pack, true);
        CopyDir(Path.Combine(RepoRoot, "templates"), Path.Combine(Pack, "templates"));
        CopyDir(Path.Combine(RepoRoot, "static"), Path.Combine(Pack, "static"));
        CopyFile("colour_scheme.xml");
        foreach (var img in new[] { "rift_avatar.jpg", "rift_avatar.png", "avatar_round.png" })
            CopyFile(Path.Combine("images", img));
        File.WriteAllText(Path.Combine(Pack, ".rift_root"), "the RIFT hub's files, packed by BuildRift.cs\n");
        // Android keeps StreamingAssets inside the APK: main.cs unpacks them with this list
        var files = Directory.GetFiles(Pack, "*", SearchOption.AllDirectories)
            .Select(f => f.Substring(Pack.Length + 1).Replace('\\', '/'))
            .Where(f => f != "files.txt" && !f.EndsWith(".meta"));
        File.WriteAllLines(Path.Combine(Pack, "files.txt"), files);
        AssetDatabase.Refresh();
        Debug.Log("[RIFT] packed the dashboard files into " + Pack);
    }

    [MenuItem("RIFT/Build Windows")]
    public static void Windows() => Build(BuildTarget.StandaloneWindows64, Path.Combine("Builds", "Windows", "RIFT.exe"));

    [MenuItem("RIFT/Build Android")]
    public static void Android() => Build(BuildTarget.Android, Path.Combine("Builds", "Android", "RIFT.apk"));

    [MenuItem("RIFT/Build Linux")]
    public static void Linux() => Build(BuildTarget.StandaloneLinux64, Path.Combine("Builds", "Linux", "RIFT.x86_64"));

    static void Build(BuildTarget target, string output)
    {
        PackFiles();
        PlayerSettings.productName = "RIFT";
        PlayerSettings.runInBackground = true;   // keep serving the fleet when the window loses focus
        var scenes = EditorBuildSettings.scenes.Where(s => s.enabled).Select(s => s.path).ToArray();
        if (scenes.Length == 0) scenes = new[] { "Assets/Scenes/SampleScene.unity" };
        var report = BuildPipeline.BuildPlayer(new BuildPlayerOptions
        {
            scenes = scenes,
            locationPathName = Path.Combine(ProjectDir, output),
            target = target,
            options = BuildOptions.None,
        });
        var s = report.summary;
        Debug.Log("[RIFT] build " + s.result + ": " + s.outputPath + " (" + s.totalErrors + " errors)");
        if (Application.isBatchMode) EditorApplication.Exit(s.result == BuildResult.Succeeded ? 0 : 1);
    }

    static void CopyFile(string rel)
    {
        var from = Path.Combine(RepoRoot, rel);
        if (!File.Exists(from)) return;
        var to = Path.Combine(Pack, rel);
        Directory.CreateDirectory(Path.GetDirectoryName(to));
        File.Copy(from, to, true);
    }

    static void CopyDir(string from, string to)
    {
        if (!Directory.Exists(from)) return;
        foreach (var f in Directory.GetFiles(from, "*", SearchOption.AllDirectories))
        {
            if (f.Contains("__pycache__")) continue;
            var dest = Path.Combine(to, f.Substring(from.Length + 1));
            Directory.CreateDirectory(Path.GetDirectoryName(dest));
            File.Copy(f, dest, true);
        }
    }
}
