using System.Security.Principal;
using DjGoo.Product;
using DjGoo.Product.Host;

var arguments = Arguments.Parse(args);
var paths = new ProductPaths(arguments.ProgramRoot, arguments.DataRoot);
paths.EnsureDataDirectories();
var log = new HostLogger(paths.HostLog);
var identity = paths.InstanceIdentity();
var user = WindowsIdentity.GetCurrent().User?.Value ?? Environment.UserName;
var mutexName = $"Local\\DjGoo.Host.{user.Replace('\\', '_')}.{identity}";
using var mutex = new Mutex(true, mutexName, out var ownsMutex);
if (!ownsMutex) return 10;

var definitions = new List<ComponentDefinition>();
if (!string.IsNullOrWhiteSpace(arguments.TestChild))
{
    var shutdownEvent = $"Local\\DjGoo.TestChild.Shutdown.{identity}";
    definitions.Add(new ComponentDefinition(ProductComponentKind.TestChild, "test-child", arguments.TestChild,
        new[] { "--shutdown-event", shutdownEvent }, Path.GetDirectoryName(arguments.TestChild) ?? paths.ProgramRoot,
        ShutdownEventName: shutdownEvent));
}

using var supervisor = new NativeSupervisor(definitions, identity, log);
using var exit = new CancellationTokenSource();
var server = new PipeServer(arguments.PipeName ?? $"DjGoo.Host.{identity}", supervisor, log, exit.Cancel);
log.Write($"host.start pid={Environment.ProcessId} program={paths.ProgramRoot} data={paths.DataRoot}");
try { await server.RunAsync(exit.Token); }
finally { log.Write("host.exit"); }
return 0;

internal sealed record Arguments(string? ProgramRoot, string? DataRoot, string? PipeName, string? TestChild)
{
    public static Arguments Parse(string[] args)
    {
        string? Value(string name)
        {
            var index = Array.FindIndex(args, value => value.Equals(name, StringComparison.OrdinalIgnoreCase));
            return index >= 0 && index + 1 < args.Length ? Path.GetFullPath(args[index + 1]) : null;
        }
        var pipeIndex = Array.FindIndex(args, value => value.Equals("--pipe-name", StringComparison.OrdinalIgnoreCase));
        var pipe = pipeIndex >= 0 && pipeIndex + 1 < args.Length ? args[pipeIndex + 1] : null;
        return new Arguments(Value("--program-root"), Value("--data-root"), pipe, Value("--test-child"));
    }
}
