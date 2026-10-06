using System.Buffers.Binary;
using System.Text.Json;

namespace DjGoo.Product;

public sealed record HostRequest(int ProtocolVersion, string Command);
public sealed record HostResponse(bool Ok, string Command, string Error, HostStatus? Status);

public static class PipeProtocol
{
    public const int Version = 1;
    public const int MaximumMessageBytes = 64 * 1024;

    public static async Task WriteAsync<T>(Stream stream, T message, CancellationToken cancellationToken)
    {
        var payload = JsonSerializer.SerializeToUtf8Bytes(message, JsonOptions.Strict);
        if (payload.Length == 0 || payload.Length > MaximumMessageBytes)
            throw new InvalidDataException("IPC message size is invalid.");
        var header = new byte[4];
        BinaryPrimitives.WriteInt32LittleEndian(header, payload.Length);
        await stream.WriteAsync(header, cancellationToken);
        await stream.WriteAsync(payload, cancellationToken);
        await stream.FlushAsync(cancellationToken);
    }

    public static async Task<T> ReadAsync<T>(Stream stream, CancellationToken cancellationToken)
    {
        var header = new byte[4];
        await ReadExactlyAsync(stream, header, cancellationToken);
        var length = BinaryPrimitives.ReadInt32LittleEndian(header);
        if (length <= 0 || length > MaximumMessageBytes)
            throw new InvalidDataException("IPC message size is invalid.");
        var payload = new byte[length];
        await ReadExactlyAsync(stream, payload, cancellationToken);
        try
        {
            return JsonSerializer.Deserialize<T>(payload, JsonOptions.Strict)
                   ?? throw new InvalidDataException("IPC message is empty.");
        }
        catch (JsonException ex)
        {
            throw new InvalidDataException("IPC message JSON is invalid.", ex);
        }
    }

    private static async Task ReadExactlyAsync(Stream stream, Memory<byte> buffer, CancellationToken token)
    {
        var offset = 0;
        while (offset < buffer.Length)
        {
            var read = await stream.ReadAsync(buffer[offset..], token);
            if (read == 0) throw new EndOfStreamException("IPC message ended early.");
            offset += read;
        }
    }
}
