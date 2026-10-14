using System.Text.Json;
using System.Text.Json.Serialization;
using System.Text.RegularExpressions;

namespace DjGoo.Product;

public sealed record LayerIdentity(
    [property: JsonPropertyName("generation")] string Generation,
    [property: JsonPropertyName("version")] string Version,
    [property: JsonPropertyName("sha256")] string Sha256,
    [property: JsonPropertyName("size")] long Size,
    [property: JsonPropertyName("location")] string Location,
    [property: JsonPropertyName("artifact")] string Artifact,
    [property: JsonPropertyName("optional")] bool Optional = false)
{
    private static readonly Regex HashPattern = new("^[0-9a-f]{64}$", RegexOptions.CultureInvariant);

    public void Validate(string name)
    {
        if (string.IsNullOrWhiteSpace(Generation) || string.IsNullOrWhiteSpace(Version))
            throw new ManifestValidationException($"{name} requires generation and version.");
        if (!HashPattern.IsMatch(Sha256 ?? string.Empty))
            throw new ManifestValidationException($"{name} has an invalid SHA-256.");
        if (Size <= 0) throw new ManifestValidationException($"{name} size must be positive.");
        ValidateRelative(name, Location);
        if (string.IsNullOrWhiteSpace(Artifact) || Path.GetFileName(Artifact) != Artifact)
            throw new ManifestValidationException($"{name} artifact identity is invalid.");
    }

    private static void ValidateRelative(string name, string value)
    {
        if (string.IsNullOrWhiteSpace(value) || Path.IsPathRooted(value) || value.Contains(':'))
            throw new ManifestValidationException($"{name} location must be relative.");
        var parts = value.Replace('\\', '/').Split('/');
        if (parts.Any(part => part is "" or "." or ".."))
            throw new ManifestValidationException($"{name} location is unsafe.");
    }
}

public sealed record ProductManifest(
    [property: JsonPropertyName("schema")] int Schema,
    [property: JsonPropertyName("application")] LayerIdentity Application,
    [property: JsonPropertyName("python_red")] LayerIdentity PythonRed,
    [property: JsonPropertyName("java")] LayerIdentity Java,
    [property: JsonPropertyName("lavalink")] LayerIdentity Lavalink,
    [property: JsonPropertyName("webrtc")] LayerIdentity WebRtc,
    [property: JsonPropertyName("speech")] LayerIdentity? Speech)
{
    public const int CurrentSchema = 1;

    public static ProductManifest ParseUnsigned(string json)
    {
        ProductManifest manifest;
        try
        {
            using var document = JsonDocument.Parse(json);
            ValidateProperties(document.RootElement,
                "schema", "application", "python_red", "java", "lavalink", "webrtc", "speech");
            foreach (var name in new[] { "application", "python_red", "java", "lavalink", "webrtc", "speech" })
            {
                if (document.RootElement.TryGetProperty(name, out var layer) && layer.ValueKind != JsonValueKind.Null)
                    ValidateProperties(layer, "generation", "version", "sha256", "size", "location", "artifact", "optional");
            }
            manifest = JsonSerializer.Deserialize<ProductManifest>(json, JsonOptions.Strict)
                       ?? throw new ManifestValidationException("Manifest is empty.");
        }
        catch (JsonException ex)
        {
            throw new ManifestValidationException("Manifest JSON is invalid.", ex);
        }
        manifest.Validate();
        return manifest;
    }

    private static void ValidateProperties(JsonElement element, params string[] allowed)
    {
        if (element.ValueKind != JsonValueKind.Object)
            throw new ManifestValidationException("Manifest object is invalid.");
        var accepted = new HashSet<string>(allowed, StringComparer.Ordinal);
        var seen = new HashSet<string>(StringComparer.Ordinal);
        foreach (var property in element.EnumerateObject())
        {
            if (!accepted.Contains(property.Name))
                throw new ManifestValidationException($"Unknown manifest field: {property.Name}.");
            if (!seen.Add(property.Name))
                throw new ManifestValidationException($"Duplicate manifest field: {property.Name}.");
        }
    }

    public void Validate()
    {
        if (Schema != CurrentSchema) throw new ManifestValidationException("Unsupported manifest schema.");
        if (Application is null || PythonRed is null || Java is null || Lavalink is null || WebRtc is null)
            throw new ManifestValidationException("Manifest is missing a required layer.");
        var layers = new Dictionary<string, LayerIdentity?>
        {
            ["application"] = Application, ["python_red"] = PythonRed, ["java"] = Java,
            ["lavalink"] = Lavalink, ["webrtc"] = WebRtc, ["speech"] = Speech,
        };
        foreach (var layer in layers.Where(item => item.Value is not null)) layer.Value!.Validate(layer.Key);
        if (Speech is not null && !Speech.Optional)
            throw new ManifestValidationException("Speech layer must be optional.");
        var locations = layers.Values.Where(value => value is not null)
            .Select(value => value!.Location).ToArray();
        if (locations.Distinct(StringComparer.OrdinalIgnoreCase).Count() != locations.Length)
            throw new ManifestValidationException("Layer locations must be unique.");
    }
}

public sealed class ManifestValidationException : Exception
{
    public ManifestValidationException(string message) : base(message) { }
    public ManifestValidationException(string message, Exception inner) : base(message, inner) { }
}

internal static class JsonOptions
{
    public static readonly JsonSerializerOptions Strict = new()
    {
        PropertyNameCaseInsensitive = false,
        WriteIndented = false,
    };
}
