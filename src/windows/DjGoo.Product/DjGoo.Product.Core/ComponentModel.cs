using System.Text.Json.Serialization;

namespace DjGoo.Product;

[JsonConverter(typeof(JsonStringEnumConverter))]
public enum ComponentPhase
{
    Stopped,
    Starting,
    Running,
    Recovering,
    NeedsAttention,
    Stopping,
}

public enum ProductComponentKind
{
    Red,
    Lavalink,
    WebRemote,
    LocalVoice,
    TestChild,
}

public sealed record ProductComponentDescriptor(
    ProductComponentKind Kind,
    string Name,
    bool Optional,
    IReadOnlyList<ProductComponentKind> Dependencies);

public static class ProductComponentCatalog
{
    public static readonly IReadOnlyList<ProductComponentDescriptor> All = new[]
    {
        new ProductComponentDescriptor(ProductComponentKind.Lavalink, "lavalink", false, Array.Empty<ProductComponentKind>()),
        new ProductComponentDescriptor(ProductComponentKind.Red, "red", false, new[] { ProductComponentKind.Lavalink }),
        new ProductComponentDescriptor(ProductComponentKind.WebRemote, "web-remote", false, new[] { ProductComponentKind.Red }),
        new ProductComponentDescriptor(ProductComponentKind.LocalVoice, "local-voice", true, new[] { ProductComponentKind.WebRemote }),
    };
}

public sealed record ComponentDefinition(
    ProductComponentKind Kind,
    string Name,
    string Executable,
    IReadOnlyList<string> Arguments,
    string WorkingDirectory,
    bool Optional = false,
    string? ShutdownEventName = null);

public sealed record ComponentStatus(
    ProductComponentKind Kind,
    string Name,
    ComponentPhase Phase,
    int? Pid,
    DateTimeOffset? StartedAt,
    int RestartCount,
    DateTimeOffset? LastHealthAt,
    string LastHealthResult,
    string LastError,
    DateTimeOffset? RetryAt);

public sealed record HostStatus(
    int ProtocolVersion,
    string HostVersion,
    int HostPid,
    bool DesiredRunning,
    IReadOnlyList<ComponentStatus> Components);
