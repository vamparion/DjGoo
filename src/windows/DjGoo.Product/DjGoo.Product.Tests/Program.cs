using System.Buffers.Binary;
using System.Diagnostics;
using System.IO.Pipes;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using DjGoo.Product;

if (args.Length != 3)
{
    Console.Error.WriteLine("Usage: DjGoo.Product.Tests.exe <host> <client> <test-child>");
    return 2;
}

var suite = new ProductTestSuite(Path.GetFullPath(args[0]), Path.GetFullPath(args[1]), Path.GetFullPath(args[2]));
await suite.RunAsync();
Console.WriteLine($"PASS {suite.Passed} native product assertions");
return 0;

internal sealed class ProductTestSuite
{
    private readonly string _host;
    private readonly string _client;
    private readonly string _child;
    private readonly string _root = Path.Combine(Path.GetTempPath(), "DjGoo-Stage1-" + Guid.NewGuid().ToString("N"));
    private int _passed;
    public int Passed => _passed;

    public ProductTestSuite(string host, string client, string child)
    {
        _host = host; _client = client; _child = child;
    }

    public async Task RunAsync()
    {
        try
        {
            UnitPaths();
            UnitDeveloperMode();
            UnitManifest();
            UnitComponentModel();
            await UnitFramingAsync();
            await IntegrationAsync();
            await HostCrashCleanupAsync();
        }
        finally
        {
            try { Directory.Delete(_root, true); } catch (IOException) { }
        }
    }

    private void UnitPaths()
    {
        var paths = new ProductPaths(Path.Combine(_root, "program"), Path.Combine(_root, "data"));
        Check(paths.ProgramRoot != paths.DataRoot, "ProgramRoot/DataRoot separation");
        paths.EnsureDataDirectories();
        foreach (var path in new[] { paths.Config, paths.Credentials, paths.Pairings, paths.Logs, paths.Health, paths.Downloads, paths.Staging, paths.Rollback })
            Check(Directory.Exists(path) && path.StartsWith(paths.DataRoot, StringComparison.OrdinalIgnoreCase), "central data path " + Path.GetFileName(path));
        Check(paths.Applications.StartsWith(paths.ProgramRoot, StringComparison.OrdinalIgnoreCase), "application layers under program root");
        Check(paths.RuntimeLayers.StartsWith(paths.ProgramRoot, StringComparison.OrdinalIgnoreCase), "runtime layers under program root");
        Throws<InvalidOperationException>(() => new ProductPaths(paths.ProgramRoot, Path.Combine(paths.ProgramRoot, "data")),
            "nested data root refusal");
    }

    private void UnitDeveloperMode()
    {
        var program = Path.Combine(_root, "developer");
        Directory.CreateDirectory(Path.Combine(program, ".git"));
        var paths = new ProductPaths(program, Path.Combine(_root, "developer-data"));
        Check(paths.IsDeveloperMode, "Developer Mode detection");
        Throws<InvalidOperationException>(() => paths.EnsureProductionMutationAllowed("repair"), "production mutation refusal");
    }

    private void UnitManifest()
    {
        const string hashA = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
        var layer = new LayerIdentity("1", "1.0", hashA, 123, "layers/app/1", "app.zip");
        var speech = new LayerIdentity("1", "1.0", hashA, 123, "layers/speech/1", "speech.zip", true);
        var manifest = new ProductManifest(1, layer,
            layer with { Location = "layers/python/1", Artifact = "python.zip" },
            layer with { Location = "layers/java/1", Artifact = "java.zip" },
            layer with { Location = "layers/lavalink/1", Artifact = "lavalink.zip" },
            layer with { Location = "layers/webrtc/1", Artifact = "webrtc.zip" }, speech);
        var json = JsonSerializer.Serialize(manifest);
        var parsed = ProductManifest.ParseUnsigned(json);
        Check(parsed.PythonRed.Generation == "1" && parsed.Speech!.Optional, "manifest parsing and layer identity");
        Throws<ManifestValidationException>(() => ProductManifest.ParseUnsigned(json.Replace(hashA, "bad")), "manifest hash validation");
        Throws<ManifestValidationException>(() => ProductManifest.ParseUnsigned(json.Replace("layers/java/1", "../java")), "manifest path validation");
        Throws<ManifestValidationException>(() => ProductManifest.ParseUnsigned(json[..^1] + ",\"unknown\":1}"), "manifest unknown field validation");
        Throws<ManifestValidationException>(() => ProductManifest.ParseUnsigned(json.Replace("\"schema\":1", "\"schema\":1,\"schema\":1")),
            "manifest duplicate field validation");
        var incomplete = JsonNode.Parse(json)!.AsObject();
        incomplete.Remove("application");
        Throws<ManifestValidationException>(() => ProductManifest.ParseUnsigned(incomplete.ToJsonString()),
            "manifest required layer validation");
    }

    private void UnitComponentModel()
    {
        var catalog = ProductComponentCatalog.All;
        Check(catalog.Select(item => item.Kind).ToHashSet().SetEquals(new[]
        {
            ProductComponentKind.Red, ProductComponentKind.Lavalink,
            ProductComponentKind.WebRemote, ProductComponentKind.LocalVoice,
        }), "production component identities");
        Check(catalog.Single(item => item.Kind == ProductComponentKind.Red).Dependencies.Contains(ProductComponentKind.Lavalink),
            "component dependency model");
        Check(catalog.Single(item => item.Kind == ProductComponentKind.LocalVoice).Optional,
            "optional local voice model");
    }

    private async Task UnitFramingAsync()
    {
        await using var stream = new MemoryStream();
        await PipeProtocol.WriteAsync(stream, new HostRequest(1, "status"), CancellationToken.None);
        stream.Position = 0;
        var request = await PipeProtocol.ReadAsync<HostRequest>(stream, CancellationToken.None);
        Check(request.Command == "status", "IPC framed round trip");
        await using var oversized = new MemoryStream();
        var header = new byte[4];
        BinaryPrimitives.WriteInt32LittleEndian(header, PipeProtocol.MaximumMessageBytes + 1);
        await oversized.WriteAsync(header);
        oversized.Position = 0;
        await ThrowsAsync<InvalidDataException>(() => PipeProtocol.ReadAsync<HostRequest>(oversized, CancellationToken.None), "IPC size limit");
        await using var malformed = new MemoryStream();
        var bytes = Encoding.UTF8.GetBytes("not-json");
        BinaryPrimitives.WriteInt32LittleEndian(header, bytes.Length);
        await malformed.WriteAsync(header); await malformed.WriteAsync(bytes); malformed.Position = 0;
        await ThrowsAsync<InvalidDataException>(() => PipeProtocol.ReadAsync<HostRequest>(malformed, CancellationToken.None), "malformed IPC JSON");
    }

    private async Task IntegrationAsync()
    {
        var program = Path.Combine(_root, "integration-program");
        var data = Path.Combine(_root, "integration-data");
        Directory.CreateDirectory(program);
        var pipe = "DjGoo.Stage1." + Guid.NewGuid().ToString("N");
        using var unrelated = Start(_child, "--run");
        using var host = Start(_host, $"--program-root \"{program}\" --data-root \"{data}\" --pipe-name {pipe} --test-child \"{_child}\"");
        await WaitForPipeAsync(pipe);
        using var duplicate = Start(_host, $"--program-root \"{program}\" --data-root \"{data}\" --pipe-name {pipe} --test-child \"{_child}\"");
        Check(duplicate.WaitForExit(5000) && duplicate.ExitCode == 10, "single Host instance");
        var hello = await SendAsync(pipe, "hello");
        Check(hello.Ok && hello.Status!.ProtocolVersion == 1, "hello/version");
        var started = await SendAsync(pipe, "start");
        var ownedPid = RunningPid(started);
        Check(Process.GetProcessById(ownedPid) is not null, "Host launches and retains child");
        await RawProtocolFailuresAsync(pipe);
        Process.GetProcessById(ownedPid).Kill(true);
        await WaitUntilAsync(async () => (await SendAsync(pipe, "status")).Status!.Components.Single().Phase == ComponentPhase.NeedsAttention);
        Check(true, "child crash detected");
        var restarted = await SendAsync(pipe, "restart");
        var restartedPid = RunningPid(restarted);
        Check(restartedPid != ownedPid, "restart replaces child");
        var stopped = await SendAsync(pipe, "stop");
        Check(stopped.Status!.Components.Single().Phase == ComponentPhase.Stopped && !ProcessExists(restartedPid), "stop cleans owned child");
        var log = await File.ReadAllTextAsync(Path.Combine(data, "logs", "host.log"));
        Check(log.Contains("component.stopped_gracefully", StringComparison.Ordinal), "clean child shutdown before force fallback");
        var startedAgain = await SendAsync(pipe, "start");
        var finalOwnedPid = RunningPid(startedAgain);
        Check(finalOwnedPid > 0, "start after stop");
        var cli = Start(_client, $"{pipe} status", redirect: true);
        var cliOutput = await cli.StandardOutput.ReadToEndAsync();
        Check(cli.WaitForExit(5000) && cli.ExitCode == 0 && cliOutput.Contains("test-child"), "separate executable IPC client");
        await SendAsync(pipe, "exit");
        Check(host.WaitForExit(10000), "Host exits by IPC");
        Check(!ProcessExists(finalOwnedPid), "Host exit kills owned child");
        Check(!unrelated.HasExited, "unrelated process remains alive");
        unrelated.Kill(true);
    }

    private async Task HostCrashCleanupAsync()
    {
        var program = Path.Combine(_root, "crash-program");
        var data = Path.Combine(_root, "crash-data");
        Directory.CreateDirectory(program);
        var pipe = "DjGoo.Stage1.Crash." + Guid.NewGuid().ToString("N");
        using var host = Start(_host, $"--program-root \"{program}\" --data-root \"{data}\" --pipe-name {pipe} --test-child \"{_child}\"");
        await WaitForPipeAsync(pipe);
        var pid = RunningPid(await SendAsync(pipe, "start"));
        host.Kill(true);
        host.WaitForExit(5000);
        await WaitUntilAsync(() => Task.FromResult(!ProcessExists(pid)));
        Check(!ProcessExists(pid), "Job Object cleans child after Host crash");
    }

    private async Task RawProtocolFailuresAsync(string pipeName)
    {
        await using (var pipe = await ConnectRawAsync(pipeName))
        {
            var header = new byte[4];
            BinaryPrimitives.WriteInt32LittleEndian(header, PipeProtocol.MaximumMessageBytes + 1);
            await pipe.WriteAsync(header); await pipe.FlushAsync();
            var response = await PipeProtocol.ReadAsync<HostResponse>(pipe, CancellationToken.None);
            Check(!response.Ok && response.Command == "invalid", "Host rejects oversized IPC");
        }
        await using (var pipe = await ConnectRawAsync(pipeName))
        {
            var payload = Encoding.UTF8.GetBytes("bad-json");
            var header = new byte[4]; BinaryPrimitives.WriteInt32LittleEndian(header, payload.Length);
            await pipe.WriteAsync(header); await pipe.WriteAsync(payload); await pipe.FlushAsync();
            var response = await PipeProtocol.ReadAsync<HostResponse>(pipe, CancellationToken.None);
            Check(!response.Ok && response.Command == "invalid", "Host rejects malformed IPC");
        }
    }

    private static async Task<NamedPipeClientStream> ConnectRawAsync(string name)
    {
        var pipe = new NamedPipeClientStream(".", name, PipeDirection.InOut, PipeOptions.Asynchronous);
        await pipe.ConnectAsync(5000);
        return pipe;
    }

    private static int RunningPid(HostResponse response)
    {
        var component = response.Status!.Components.Single();
        if (!response.Ok || component.Phase != ComponentPhase.Running || component.Pid is null)
            throw new InvalidOperationException("Component did not reach Running.");
        return component.Pid.Value;
    }

    private static async Task<HostResponse> SendAsync(string pipe, string command) =>
        await new HostPipeClient(pipe).SendAsync(command, 10000);

    private static async Task WaitForPipeAsync(string pipe)
    {
        await WaitUntilAsync(async () =>
        {
            try { return (await SendAsync(pipe, "hello")).Ok; }
            catch { return false; }
        }, 15000);
    }

    private static async Task WaitUntilAsync(Func<Task<bool>> condition, int timeout = 10000)
    {
        var deadline = DateTime.UtcNow.AddMilliseconds(timeout);
        while (DateTime.UtcNow < deadline)
        {
            if (await condition()) return;
            await Task.Delay(100);
        }
        throw new TimeoutException("Timed out waiting for native product state.");
    }

    private static Process Start(string executable, string arguments, bool redirect = false)
    {
        return Process.Start(new ProcessStartInfo(executable, arguments)
        {
            UseShellExecute = false, CreateNoWindow = true, WindowStyle = ProcessWindowStyle.Hidden,
            RedirectStandardOutput = redirect, RedirectStandardError = redirect,
        }) ?? throw new InvalidOperationException("Could not launch " + executable);
    }

    private static bool ProcessExists(int pid)
    {
        try { return !Process.GetProcessById(pid).HasExited; }
        catch (ArgumentException) { return false; }
    }

    private void Check(bool condition, string name)
    {
        if (!condition) throw new InvalidOperationException("FAIL: " + name);
        _passed++; Console.WriteLine("PASS " + name);
    }

    private void Throws<T>(Action action, string name) where T : Exception
    {
        try { action(); }
        catch (T) { Check(true, name); return; }
        throw new InvalidOperationException("FAIL: " + name);
    }

    private async Task ThrowsAsync<T>(Func<Task> action, string name) where T : Exception
    {
        try { await action(); }
        catch (T) { Check(true, name); return; }
        throw new InvalidOperationException("FAIL: " + name);
    }
}
