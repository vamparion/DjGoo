using System.IO.Pipes;

namespace DjGoo.Product.Host;

internal sealed class PipeServer
{
    private readonly string _name;
    private readonly NativeSupervisor _supervisor;
    private readonly HostLogger _log;
    private readonly Action _requestExit;

    public PipeServer(string name, NativeSupervisor supervisor, HostLogger log, Action requestExit)
    {
        _name = name; _supervisor = supervisor; _log = log; _requestExit = requestExit;
    }

    public async Task RunAsync(CancellationToken token)
    {
        while (!token.IsCancellationRequested)
        {
            await using var pipe = new NamedPipeServerStream(_name, PipeDirection.InOut, 4,
                PipeTransmissionMode.Byte, PipeOptions.Asynchronous | PipeOptions.CurrentUserOnly);
            try
            {
                await pipe.WaitForConnectionAsync(token);
                await HandleAsync(pipe, token);
            }
            catch (OperationCanceledException) when (token.IsCancellationRequested) { break; }
            catch (Exception ex) { _log.Write($"ipc.error {ex}"); }
        }
    }

    private async Task HandleAsync(Stream pipe, CancellationToken token)
    {
        HostResponse response;
        try
        {
            var request = await PipeProtocol.ReadAsync<HostRequest>(pipe, token);
            if (request.ProtocolVersion != PipeProtocol.Version)
                response = new HostResponse(false, request.Command, "Unsupported protocol version.", _supervisor.Snapshot());
            else
                response = Dispatch(request.Command);
        }
        catch (InvalidDataException ex)
        {
            response = new HostResponse(false, "invalid", ex.Message, _supervisor.Snapshot());
        }
        catch (Exception ex)
        {
            _log.Write($"ipc.command_failed {ex}");
            response = new HostResponse(false, "error", ex.Message, _supervisor.Snapshot());
        }
        await PipeProtocol.WriteAsync(pipe, response, token);
        if (response.Ok && response.Command == "exit") _requestExit();
    }

    private HostResponse Dispatch(string command)
    {
        var normalized = (command ?? string.Empty).Trim().ToLowerInvariant();
        HostStatus status;
        switch (normalized)
        {
            case "hello": case "status": status = _supervisor.Snapshot(); break;
            case "start": status = _supervisor.Start(); break;
            case "stop": status = _supervisor.Stop(); break;
            case "restart": status = _supervisor.Restart(); break;
            case "exit":
                status = _supervisor.Stop();
                break;
            default: return new HostResponse(false, normalized, "Unknown command.", _supervisor.Snapshot());
        }
        return new HostResponse(true, normalized, string.Empty, status);
    }
}
