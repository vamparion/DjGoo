using System.Text.Json;

namespace DjGoo.Product;

public sealed class InstalledProduct
{
    public InstalledProduct(ProductPaths paths)
    {
        Paths = paths;
        var manifestPath = Path.Combine(paths.ProgramRoot, "product-manifest.json");
        Manifest = ProductManifest.ParseUnsigned(File.ReadAllText(manifestPath));
    }

    public ProductPaths Paths { get; }
    public ProductManifest Manifest { get; }

    public string Layer(LayerIdentity identity) => SafeProgramPath(identity.Location);
    public string ApplicationRoot => Layer(Manifest.Application);
    public string PythonRoot => Layer(Manifest.PythonRed);
    public string JavaRoot => Layer(Manifest.Java);
    public string LavalinkRoot => Layer(Manifest.Lavalink);
    public string WebRtcRoot => Layer(Manifest.WebRtc);

    public string SafeProgramPath(string relative)
    {
        var root = Path.GetFullPath(Paths.ProgramRoot).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
        var path = Path.GetFullPath(Path.Combine(Paths.ProgramRoot, relative));
        if (!path.StartsWith(root, StringComparison.OrdinalIgnoreCase))
            throw new ManifestValidationException("Layer path escapes the DjGoo program root.");
        return path;
    }

    public IReadOnlyList<ComponentDefinition> Components()
    {
        var python = Path.Combine(PythonRoot, "pythonw.exe");
        if (!File.Exists(python)) python = Path.Combine(PythonRoot, "python.exe");
        var java = Path.Combine(JavaRoot, "bin", "java.exe");
        var lavalinkJar = Path.Combine(LavalinkRoot, "Lavalink.jar");
        var lavalinkConfig = Path.Combine(LavalinkRoot, "application.yml");
        var health = Paths.Health;
        var pythonPaths = new List<string>
        {
            ApplicationRoot,
            Path.Combine(WebRtcRoot, "Lib", "site-packages"),
        };
        string? speechRoot = null;
        if (Manifest.Speech is not null)
        {
            speechRoot = Layer(Manifest.Speech);
            pythonPaths.Add(Path.Combine(speechRoot, "Lib", "site-packages"));
        }
        var environment = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
        {
            ["DJGOO_PROGRAM_ROOT"] = Paths.ProgramRoot,
            ["DJGOO_DATA_ROOT"] = Paths.DataRoot,
            ["DJGOO_HOME"] = Paths.ProgramRoot,
            ["DJGOO_APP_ROOT"] = ApplicationRoot,
            ["DJGOO_HEALTH_DIR"] = health,
            ["DJGOO_SECRETS_FILE"] = Path.Combine(Paths.Config, "secrets.json"),
            ["DJGOO_EVENT_LOG"] = Path.Combine(Paths.Logs, "djgoo-events.jsonl"),
            ["DJGOO_JAVA"] = java,
            ["DJGOO_NATIVE_HOST"] = "1",
            ["PYTHONUTF8"] = "1",
            ["PYTHONIOENCODING"] = "utf-8:backslashreplace",
            ["PYTHONDONTWRITEBYTECODE"] = "1",
            ["PYTHONPATH"] = string.Join(Path.PathSeparator, pythonPaths),
            ["REDBOT_CONFIG_DIR"] = Path.Combine(Paths.DataRoot, ".localappdata", "Red-DiscordBot", "Red-DiscordBot"),
        };
        Directory.CreateDirectory(Path.Combine(Paths.DataRoot, "data", "discordbot", "cogs", "Audio"));

        var components = new List<ComponentDefinition>
        {
            new ComponentDefinition(ProductComponentKind.Lavalink, "lavalink", java,
                new[] { "-Xms64M", "-Xmx512M", "-jar", lavalinkJar, $"--spring.config.location=file:{lavalinkConfig.Replace('\\', '/')}" },
                LavalinkRoot, Environment: environment, Health: new(ComponentHealthKind.Tcp, "::1", 2333), StartupTimeoutSeconds: 60),
            new ComponentDefinition(ProductComponentKind.Red, "red", python,
                new[] { Path.Combine(ApplicationRoot, "tools", "start_redbot_selector.py") }, ApplicationRoot,
                Environment: environment, Dependencies: new[] { "lavalink" },
                Health: new(ComponentHealthKind.Heartbeat, Path.Combine(health, "redbot.json"), MaximumAgeSeconds: 60), StartupTimeoutSeconds: 150),
            new ComponentDefinition(ProductComponentKind.WebRemote, "web-remote", python,
                new[] { "-m", "control_panel.server", "--project-root", Paths.DataRoot, "--static-root", Path.Combine(ApplicationRoot, "control_panel_dist"), "--host", "127.0.0.1", "--port", "8765", "--tls" },
                ApplicationRoot, Environment: environment, Dependencies: new[] { "red" },
                Health: new(ComponentHealthKind.Https, "https://127.0.0.1:8765/api/healthz"), StartupTimeoutSeconds: 45),
        };
        if (speechRoot is not null)
            components.Add(new ComponentDefinition(ProductComponentKind.LocalVoice, "local-voice", python,
                new[] { "-m", "voice.djgoo_voice_listener", "--project-root", Paths.DataRoot }, ApplicationRoot, true,
                Environment: environment, Dependencies: new[] { "web-remote" },
                Health: new(ComponentHealthKind.Heartbeat, Path.Combine(health, "voice.json"), MaximumAgeSeconds: 90), StartupTimeoutSeconds: 180));
        return components;
    }
}
