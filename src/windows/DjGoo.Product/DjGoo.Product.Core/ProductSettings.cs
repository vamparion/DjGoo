using System.Text.Json;
using System.Text.Json.Nodes;

namespace DjGoo.Product;

public sealed record ProductSettings(
    bool HasToken,
    string Prefix,
    string Locale,
    bool Embeds,
    bool Fuzzy,
    bool UseButtons,
    bool InvitePublic,
    string Description);

public static class ProductSettingsStore
{
    public static string SettingsPath(ProductPaths paths) =>
        Path.Combine(paths.DataRoot, "data", "discordbot", "core", "settings.json");

    public static ProductSettings Load(ProductPaths paths)
    {
        var global = ReadGlobal(SettingsPath(paths), out _);
        return new ProductSettings(
            HasToken: !string.IsNullOrWhiteSpace(global["token"]?.GetValue<string>()),
            Prefix: ReadFirstString(global["prefix"]) ?? "!",
            Locale: global["locale"]?.GetValue<string>() ?? "en-US",
            Embeds: global["embeds"]?.GetValue<bool>() ?? true,
            Fuzzy: global["fuzzy"]?.GetValue<bool>() ?? true,
            UseButtons: global["use_buttons"]?.GetValue<bool>() ?? true,
            InvitePublic: global["invite_public"]?.GetValue<bool>() ?? false,
            Description: global["description"]?.GetValue<string>() ?? string.Empty);
    }

    public static void Save(ProductPaths paths, ProductSettings settings, string? replacementToken = null)
    {
        if (string.IsNullOrWhiteSpace(settings.Prefix))
            throw new ArgumentException("Command prefix cannot be empty.", nameof(settings));
        if (string.IsNullOrWhiteSpace(settings.Locale))
            throw new ArgumentException("Locale cannot be empty.", nameof(settings));
        if (!string.IsNullOrEmpty(replacementToken) && replacementToken.Trim().Length < 20)
            throw new ArgumentException("The Discord bot token is too short.", nameof(replacementToken));

        var path = SettingsPath(paths);
        var global = ReadGlobal(path, out var root);
        if (!string.IsNullOrWhiteSpace(replacementToken)) global["token"] = replacementToken.Trim();
        global["prefix"] = new JsonArray(settings.Prefix.Trim());
        global["locale"] = settings.Locale.Trim();
        global["embeds"] = settings.Embeds;
        global["fuzzy"] = settings.Fuzzy;
        global["use_buttons"] = settings.UseButtons;
        global["invite_public"] = settings.InvitePublic;
        global["description"] = settings.Description.Trim();
        global["packages"] ??= new JsonArray("audio", "djgoowelcome");

        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        var temporary = path + ".tmp";
        File.WriteAllText(temporary, root.ToJsonString(new JsonSerializerOptions { WriteIndented = true }) + Environment.NewLine);
        File.Move(temporary, path, true);
    }

    private static JsonObject ReadGlobal(string path, out JsonObject root)
    {
        try { root = JsonNode.Parse(File.ReadAllText(path))?.AsObject() ?? new JsonObject(); }
        catch (Exception ex) when (ex is IOException or JsonException) { root = new JsonObject(); }
        var instance = root["0"] as JsonObject ?? new JsonObject();
        root["0"] = instance;
        var global = instance["GLOBAL"] as JsonObject ?? new JsonObject();
        instance["GLOBAL"] = global;
        return global;
    }

    private static string? ReadFirstString(JsonNode? node) => node switch
    {
        JsonArray array when array.Count > 0 => array[0]?.GetValue<string>(),
        JsonValue value => value.GetValue<string>(),
        _ => null,
    };
}
