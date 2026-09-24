using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Text.RegularExpressions;
using System.Windows.Forms;

internal static class DjGooThinLauncher
{
    private static string Quote(string value)
    {
        if (String.IsNullOrEmpty(value)) return "\"\"";
        if (value.IndexOfAny(new[] { ' ', '\t', '\n', '\v', '\"' }) < 0) return value;
        return "\"" + value.Replace("\\", "\\\\").Replace("\"", "\\\"") + "\"";
    }

    private static string ActiveAppRoot(string root)
    {
        string current = Path.Combine(root, "current.json");
        if (!File.Exists(current)) return root;
        try
        {
            string json = File.ReadAllText(current);
            Match match = Regex.Match(json, "\\\"path\\\"\\s*:\\s*\\\"([^\\\"]+)\\\"");
            if (!match.Success) return root;
            string relative = match.Groups[1].Value.Replace('/', Path.DirectorySeparatorChar);
            string candidate = Path.GetFullPath(Path.Combine(root, relative));
            string prefix = root.TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
            if (!candidate.StartsWith(prefix, StringComparison.OrdinalIgnoreCase)) return root;
            return Directory.Exists(candidate) ? candidate : root;
        }
        catch
        {
            return root;
        }
    }

    private static string FirstExisting(params string[] candidates)
    {
        foreach (string candidate in candidates)
        {
            if (File.Exists(candidate)) return candidate;
        }
        return candidates[candidates.Length - 1];
    }

    [STAThread]
    private static int Main(string[] args)
    {
        string executable = Process.GetCurrentProcess().MainModule.FileName;
        string root = Path.GetDirectoryName(executable);
        string name = Path.GetFileNameWithoutExtension(executable).ToLowerInvariant();
        bool voice = name.Contains("voice");
        bool mini = name.Contains("mini");
        string module = voice
            ? "launcher.djgoo_layered_voice"
            : mini ? "launcher.djgoo_layered_mini" : "launcher.djgoo_layered_host";
        string runtimeName = voice ? "python-voice" : "python-bot";
        var runtimeCandidates = new List<string>
        {
            Path.Combine(root, "runtime", runtimeName, "pythonw.exe"),
            Path.Combine(root, "runtime", "python", "pythonw.exe"),
            Path.Combine(root, "runtime", runtimeName, "python.exe"),
            Path.Combine(root, "runtime", "python", "python.exe")
        };
        bool sourceCheckout =
            Directory.Exists(Path.Combine(root, ".git")) ||
            File.Exists(Path.Combine(root, ".git"));
        if (sourceCheckout)
        {
            string sourceRuntime = voice ? ".voice-venv" : ".venv";
            runtimeCandidates.Add(Path.Combine(root, sourceRuntime, "Scripts", "pythonw.exe"));
            runtimeCandidates.Add(Path.Combine(root, sourceRuntime, "Scripts", "python.exe"));
        }
        string pythonw = FirstExisting(runtimeCandidates.ToArray());
        if (!File.Exists(pythonw))
        {
            MessageBox.Show(
                "DjGoo's portable Python runtime is missing. Re-extract the full package or repair the runtime layer.",
                "DjGoo",
                MessageBoxButtons.OK,
                MessageBoxIcon.Error
            );
            return 2;
        }

        string appRoot = ActiveAppRoot(root);
        var forwarded = new List<string>();
        forwarded.Add("-m");
        forwarded.Add(module);
        foreach (string arg in args) forwarded.Add(arg);

        var start = new ProcessStartInfo();
        start.FileName = pythonw;
        start.WorkingDirectory = root;
        start.UseShellExecute = false;
        start.CreateNoWindow = true;
        start.EnvironmentVariables["DJGOO_HOME"] = root;
        start.EnvironmentVariables["DJGOO_APP_ROOT"] = appRoot;
        string speech = Path.Combine(root, "runtime", "speech", "Lib", "site-packages");
        string webrtc = Path.Combine(root, "runtime", "webrtc", "Lib", "site-packages");
        string existing = start.EnvironmentVariables["PYTHONPATH"] ?? "";
        var pythonPath = new List<string>();
        pythonPath.Add(appRoot);
        if (Directory.Exists(webrtc)) pythonPath.Add(webrtc);
        if (Directory.Exists(speech)) pythonPath.Add(speech);
        if (!String.IsNullOrWhiteSpace(existing)) pythonPath.Add(existing);
        start.EnvironmentVariables["PYTHONPATH"] = String.Join(Path.PathSeparator.ToString(), pythonPath.ToArray());

        var command = new List<string>();
        foreach (string value in forwarded) command.Add(Quote(value));
        start.Arguments = String.Join(" ", command.ToArray());
        try
        {
            Process.Start(start);
            return 0;
        }
        catch (Exception error)
        {
            MessageBox.Show(
                "DjGoo could not start its application layer.\n\n" + error.Message,
                "DjGoo",
                MessageBoxButtons.OK,
                MessageBoxIcon.Error
            );
            return 3;
        }
    }
}
