using System.Diagnostics;
using System.Net.Security;
using System.Net.Sockets;
using System.Text.Json;

namespace DjGoo.Product.Host;

internal sealed class NativeSupervisor : IDisposable
{
    private sealed class OwnedComponent
    {
        public OwnedComponent(ComponentDefinition definition) => Definition = definition;
        public ComponentDefinition Definition { get; }
        public Process? Process { get; set; }
        public ComponentPhase Phase { get; set; } = ComponentPhase.Stopped;
        public DateTimeOffset? StartedAt { get; set; }
        public int RestartCount { get; set; }
        public DateTimeOffset? LastHealthAt { get; set; }
        public string LastHealthResult { get; set; } = "not-checked";
        public string LastError { get; set; } = string.Empty;
        public DateTimeOffset? RetryAt { get; set; }
        public EventWaitHandle? ShutdownEvent { get; set; }
    }

    private readonly object _gate = new();
    private readonly Dictionary<string, OwnedComponent> _components;
    private readonly WindowsJob _job;
    private readonly HostLogger _log;
    private readonly Timer _monitor;
    private bool _desiredRunning;
    private bool _disposed;

    public NativeSupervisor(IEnumerable<ComponentDefinition> definitions, string instanceIdentity, HostLogger log)
    {
        _components = definitions.ToDictionary(
            item => item.Name,
            item => new OwnedComponent(item),
            StringComparer.OrdinalIgnoreCase);
        _job = new WindowsJob($"Local\\DjGoo.Host.Job.{instanceIdentity}");
        _log = log;
        _monitor = new Timer(_ => Monitor(), null, TimeSpan.FromSeconds(1), TimeSpan.FromSeconds(2));
    }

    public HostStatus Snapshot()
    {
        lock (_gate)
        {
            return new HostStatus(PipeProtocol.Version, "0.3.0-alpha.29-product", Environment.ProcessId, _desiredRunning,
                _components.Values.Select(item => new ComponentStatus(
                    item.Definition.Kind, item.Definition.Name, item.Phase, IsAlive(item.Process) ? item.Process!.Id : null,
                    item.StartedAt, item.RestartCount, item.LastHealthAt, item.LastHealthResult,
                    item.LastError, item.RetryAt)).ToArray());
        }
    }

    public HostStatus Start()
    {
        lock (_gate)
        {
            ThrowIfDisposed();
            _desiredRunning = true;
            foreach (var item in _components.Values) StartOne(item, false);
            return Snapshot();
        }
    }

    public HostStatus Stop()
    {
        lock (_gate)
        {
            _desiredRunning = false;
            foreach (var item in _components.Values.Reverse()) StopOne(item);
            return Snapshot();
        }
    }

    public HostStatus Restart()
    {
        lock (_gate)
        {
            _desiredRunning = true;
            foreach (var item in _components.Values.Reverse()) StopOne(item);
            foreach (var item in _components.Values) StartOne(item, true);
            return Snapshot();
        }
    }

    private void StartOne(OwnedComponent item, bool restart)
    {
        if (IsAlive(item.Process)) return;
        if ((item.Definition.Dependencies ?? Array.Empty<string>()).Any(name =>
                !_components.TryGetValue(name, out var dependency) || dependency.Phase != ComponentPhase.Running))
            return;
        item.Phase = restart ? ComponentPhase.Recovering : ComponentPhase.Starting;
        item.LastError = string.Empty;
        var start = new ProcessStartInfo
        {
            FileName = item.Definition.Executable,
            WorkingDirectory = item.Definition.WorkingDirectory,
            UseShellExecute = false,
            CreateNoWindow = true,
            WindowStyle = ProcessWindowStyle.Hidden,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
        };
        foreach (var pair in item.Definition.Environment ?? new Dictionary<string, string>())
            start.Environment[pair.Key] = pair.Value;
        foreach (var argument in item.Definition.Arguments) start.ArgumentList.Add(argument);
        Process? process = null;
        try
        {
            if (!string.IsNullOrWhiteSpace(item.Definition.ShutdownEventName))
                item.ShutdownEvent = new EventWaitHandle(false, EventResetMode.AutoReset, item.Definition.ShutdownEventName);
            process = Process.Start(start) ?? throw new InvalidOperationException("Windows did not create the child process.");
            process.OutputDataReceived += (_, eventArgs) =>
            {
                if (eventArgs.Data is not null) _log.Write($"component.output name={item.Definition.Name} {eventArgs.Data}");
            };
            process.ErrorDataReceived += (_, eventArgs) =>
            {
                if (eventArgs.Data is not null) _log.Write($"component.error name={item.Definition.Name} {eventArgs.Data}");
            };
            process.BeginOutputReadLine();
            process.BeginErrorReadLine();
            process.EnableRaisingEvents = true;
            process.Exited += (_, _) => ChildExited(item, process);
            _job.Add(process);
            item.Process = process;
            item.StartedAt = DateTimeOffset.Now;
            if (restart) item.RestartCount++;
            item.LastHealthAt = DateTimeOffset.Now;
            item.LastHealthResult = item.Definition.Health is null ? "process-running" : "starting";
            item.Phase = item.Definition.Health is null ? ComponentPhase.Running : item.Phase;
            item.RetryAt = null;
            _log.Write($"component.start name={item.Definition.Name} pid={process.Id}");
        }
        catch (Exception ex)
        {
            if (process is not null)
            {
                try
                {
                    if (!process.HasExited) process.Kill(true);
                }
                catch (InvalidOperationException) { }
                finally { process.Dispose(); }
            }
            item.ShutdownEvent?.Dispose();
            item.ShutdownEvent = null;
            item.Phase = item.Definition.Kind == ProductComponentKind.TestChild
                ? ComponentPhase.NeedsAttention : ComponentPhase.Recovering;
            item.LastError = ex.Message;
            item.LastHealthAt = DateTimeOffset.Now;
            item.LastHealthResult = "start-failed";
            item.RetryAt = item.Definition.Kind == ProductComponentKind.TestChild
                ? null : DateTimeOffset.Now.AddSeconds(RecoveryDelay(item.RestartCount));
            _log.Write($"component.start_failed name={item.Definition.Name} error={ex}");
        }
    }

    private void ChildExited(OwnedComponent item, Process process)
    {
        lock (_gate)
        {
            if (!ReferenceEquals(item.Process, process)) return;
            var code = SafeExitCode(process);
            item.Process = null;
            item.LastHealthAt = DateTimeOffset.Now;
            item.LastHealthResult = "process-exited";
            if (item.Phase == ComponentPhase.Stopping || !_desiredRunning)
            {
                item.Phase = ComponentPhase.Stopped;
                item.LastError = string.Empty;
            }
            else
            {
                item.Phase = item.Definition.Kind == ProductComponentKind.TestChild
                    ? ComponentPhase.NeedsAttention : ComponentPhase.Recovering;
                item.LastError = $"Process exited unexpectedly with code {code}.";
                item.RetryAt = item.Definition.Kind == ProductComponentKind.TestChild
                    ? null : DateTimeOffset.Now.AddSeconds(RecoveryDelay(item.RestartCount));
            }
            item.ShutdownEvent?.Dispose();
            item.ShutdownEvent = null;
            process.Dispose();
            _log.Write($"component.exit name={item.Definition.Name} code={code} phase={item.Phase}");
        }
    }

    private void StopOne(OwnedComponent item)
    {
        var process = item.Process;
        if (!IsAlive(process))
        {
            item.Process = null;
            item.Phase = ComponentPhase.Stopped;
            return;
        }
        item.Phase = ComponentPhase.Stopping;
        item.Process = null;
        _log.Write($"component.stop name={item.Definition.Name} pid={process!.Id}");
        try
        {
            process.EnableRaisingEvents = false;
            if (item.ShutdownEvent is not null)
            {
                item.ShutdownEvent.Set();
                if (process.WaitForExit(5000))
                    _log.Write($"component.stopped_gracefully name={item.Definition.Name} pid={process.Id}");
            }
            if (!process.HasExited)
            {
                _log.Write($"component.force_stop name={item.Definition.Name} pid={process.Id}");
                process.Kill(true);
                process.WaitForExit(5000);
            }
        }
        catch (InvalidOperationException) { }
        finally
        {
            try
            {
                if (!process.HasExited) process.Kill(true);
            }
            catch (InvalidOperationException) { }
            item.Phase = ComponentPhase.Stopped;
            item.ShutdownEvent?.Dispose();
            item.ShutdownEvent = null;
            process.Dispose();
        }
    }

    private static bool IsAlive(Process? process)
    {
        if (process is null) return false;
        try { return !process.HasExited; }
        catch (InvalidOperationException) { return false; }
    }

    private static int SafeExitCode(Process process)
    {
        try { return process.ExitCode; }
        catch (InvalidOperationException) { return -1; }
    }

    private void Monitor()
    {
        lock (_gate)
        {
            if (_disposed || !_desiredRunning) return;
            foreach (var item in _components.Values)
            {
                if (!IsAlive(item.Process))
                {
                    if (item.Definition.Kind != ProductComponentKind.TestChild &&
                        (item.RetryAt is null || item.RetryAt <= DateTimeOffset.Now))
                        StartOne(item, item.StartedAt is not null);
                    continue;
                }

                var healthy = IsHealthy(item);
                item.LastHealthAt = DateTimeOffset.Now;
                item.LastHealthResult = healthy ? "healthy" : "starting";
                if (healthy)
                {
                    item.Phase = ComponentPhase.Running;
                    item.LastError = string.Empty;
                    item.RetryAt = null;
                    continue;
                }

                var elapsed = DateTimeOffset.Now - (item.StartedAt ?? DateTimeOffset.Now);
                if (elapsed.TotalSeconds <= item.Definition.StartupTimeoutSeconds) continue;
                item.LastError = "Component did not become healthy.";
                _log.Write($"component.unhealthy name={item.Definition.Name} elapsed={elapsed.TotalSeconds:F0}");
                StopOne(item);
                item.Phase = ComponentPhase.Recovering;
                item.RetryAt = DateTimeOffset.Now.AddSeconds(RecoveryDelay(item.RestartCount));
            }
        }
    }

    private bool IsHealthy(OwnedComponent item)
    {
        var health = item.Definition.Health;
        if (health is null) return IsAlive(item.Process);
        try
        {
            return health.Kind switch
            {
                ComponentHealthKind.Process => IsAlive(item.Process),
                ComponentHealthKind.Tcp => TcpHealthy(health.Target, health.Port),
                ComponentHealthKind.Https => HttpHealthy(health.Target),
                ComponentHealthKind.Heartbeat => HeartbeatHealthy(health.Target, health.MaximumAgeSeconds),
                _ => false,
            };
        }
        catch (Exception)
        {
            return false;
        }
    }

    private static bool TcpHealthy(string host, int port)
    {
        using var client = new TcpClient(AddressFamily.InterNetworkV6);
        return client.ConnectAsync(host, port).Wait(TimeSpan.FromMilliseconds(400)) && client.Connected;
    }

    private static bool HttpHealthy(string url)
    {
        using var handler = new HttpClientHandler
        {
            ServerCertificateCustomValidationCallback = (_, _, _, errors) =>
                errors == SslPolicyErrors.None || new Uri(url).IsLoopback,
        };
        using var client = new HttpClient(handler) { Timeout = TimeSpan.FromSeconds(1) };
        using var response = client.GetAsync(url).GetAwaiter().GetResult();
        return response.IsSuccessStatusCode;
    }

    private static bool HeartbeatHealthy(string path, int maximumAgeSeconds)
    {
        using var document = JsonDocument.Parse(File.ReadAllText(path));
        var root = document.RootElement;
        var timestamp = root.GetProperty("timestamp").GetDouble();
        var age = DateTimeOffset.UtcNow - DateTimeOffset.FromUnixTimeMilliseconds((long)(timestamp * 1000));
        return age >= TimeSpan.FromSeconds(-5) && age <= TimeSpan.FromSeconds(maximumAgeSeconds) &&
               (!root.TryGetProperty("ready", out var ready) || ready.GetBoolean());
    }

    private static int RecoveryDelay(int restartCount) => Math.Min(30, 2 << Math.Min(4, restartCount));

    private void ThrowIfDisposed()
    {
        if (_disposed) throw new ObjectDisposedException(nameof(NativeSupervisor));
    }

    public void Dispose()
    {
        lock (_gate)
        {
            if (_disposed) return;
            _desiredRunning = false;
            _monitor.Dispose();
            foreach (var item in _components.Values.Reverse()) StopOne(item);
            _job.Dispose();
            _disposed = true;
        }
    }
}
