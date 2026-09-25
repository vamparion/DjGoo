using System.IO.Pipes;

namespace DjGoo.Product;

public sealed class HostPipeClient
{
    private readonly string _pipeName;
    public HostPipeClient(string pipeName) => _pipeName = pipeName;

    public async Task<HostResponse> SendAsync(string command, int timeoutMilliseconds = 5000)
    {
        using var timeout = new CancellationTokenSource(timeoutMilliseconds);
        await using var pipe = new NamedPipeClientStream(".", _pipeName, PipeDirection.InOut, PipeOptions.Asynchronous);
        await pipe.ConnectAsync(timeout.Token);
        await PipeProtocol.WriteAsync(pipe, new HostRequest(PipeProtocol.Version, command), timeout.Token);
        return await PipeProtocol.ReadAsync<HostResponse>(pipe, timeout.Token);
    }
}
