using System.Diagnostics;
using System.IO.Compression;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using DjGoo.Product;

namespace DjGoo.Product.Updater;

internal sealed class UpdateEngine
{
    private readonly ProductPaths _paths;

    public UpdateEngine(ProductPaths paths) => _paths = paths;

    public async Task<bool> ApplyAsync(string feedLocation)
    {
        _paths.EnsureProductionMutationAllowed("update");
        _paths.EnsureDataDirectories();
        using var feed = JsonDocument.Parse(await ReadTextAsync(feedLocation));
        var root = feed.RootElement;
        if (root.GetProperty("schema").GetInt32() != 1) throw new InvalidDataException("Unsupported update feed schema.");
        var manifestElement = root.GetProperty("manifest");
        var manifestJson = manifestElement.GetRawText();
        VerifySignature(manifestJson, root.GetProperty("signature").GetString() ?? "");
        var next = ProductManifest.ParseUnsigned(manifestJson);
        var current = new InstalledProduct(_paths).Manifest;
        var artifacts = root.GetProperty("artifacts");
        var changed = Layers(next).Where(nextLayer => !Layers(current).Any(old => Same(old, nextLayer))).ToArray();
        if (changed.Length == 0) return false;

        var transaction = Path.Combine(_paths.Staging, Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(transaction);
        var prepared = new List<(LayerIdentity Layer, string Staged)>();
        try
        {
            foreach (var layer in changed)
            {
                var source = artifacts.GetProperty(layer.Artifact).GetString()
                             ?? throw new InvalidDataException($"Missing artifact URL for {layer.Artifact}.");
                var archive = Path.Combine(_paths.Downloads, layer.Artifact);
                await DownloadAsync(source, archive);
                var staged = Path.Combine(transaction, prepared.Count.ToString());
                ZipFile.ExtractToDirectory(archive, staged);
                LayerVerifier.Verify(staged, layer);
                prepared.Add((layer, staged));
            }
            await StopProductAsync();
            foreach (var item in prepared)
            {
                var destination = SafeProgramPath(item.Layer.Location);
                if (!Directory.Exists(destination))
                {
                    Directory.CreateDirectory(Path.GetDirectoryName(destination)!);
                    Directory.Move(item.Staged, destination);
                }
                LayerVerifier.Verify(destination, item.Layer);
            }
            var manifestPath = Path.Combine(_paths.ProgramRoot, "product-manifest.json");
            var backup = Path.Combine(_paths.Rollback, "product-manifest.json");
            File.Copy(manifestPath, backup, true);
            var temporary = manifestPath + ".new";
            await File.WriteAllTextAsync(temporary, manifestJson + Environment.NewLine, Encoding.UTF8);
            File.Move(temporary, manifestPath, true);
            try { await StartAndHealthCheckAsync(); }
            catch
            {
                await StopHostAsync();
                File.Copy(backup, manifestPath, true);
                await StartAndHealthCheckAsync();
                throw;
            }
            return true;
        }
        finally { try { Directory.Delete(transaction, true); } catch { } }
    }

    private void VerifySignature(string manifest, string encoded)
    {
        var keyPath = Path.Combine(_paths.ProgramRoot, "release-public-key.pem");
        using var rsa = RSA.Create();
        rsa.ImportFromPem(File.ReadAllText(keyPath));
        byte[] signature;
        try { signature = Convert.FromBase64String(encoded); }
        catch (FormatException ex) { throw new CryptographicException("Update signature is invalid.", ex); }
        if (!rsa.VerifyData(Encoding.UTF8.GetBytes(manifest), signature, HashAlgorithmName.SHA256, RSASignaturePadding.Pkcs1))
            throw new CryptographicException("Update signature verification failed.");
    }

    private async Task StopProductAsync()
    {
        try { EventWaitHandle.OpenExisting($"Local\\DjGoo.ControlCenter.Exit.{_paths.InstanceIdentity()}").Set(); }
        catch (WaitHandleCannotBeOpenedException) { }
        await StopHostAsync();
        await Task.Delay(500);
    }

    private async Task StopHostAsync()
    {
        try { await new HostPipeClient(PipeName()).SendAsync("exit", 15000); }
        catch (Exception ex) when (ex is TimeoutException or IOException) { }
    }

    private async Task StartAndHealthCheckAsync()
    {
        Process.Start(new ProcessStartInfo(Path.Combine(_paths.ProgramRoot, "DjGoo.Host.exe"))
        { UseShellExecute = false, CreateNoWindow = true, WorkingDirectory = _paths.ProgramRoot });
        var client = new HostPipeClient(PipeName());
        var deadline = DateTime.UtcNow.AddMinutes(3);
        while (DateTime.UtcNow < deadline)
        {
            try
            {
                var response = await client.SendAsync("start", 5000);
                var required = response.Status!.Components.Where(item => item.Kind != ProductComponentKind.LocalVoice).ToArray();
                if (required.Length > 0 && required.All(item => item.Phase == ComponentPhase.Running)) return;
                if (required.Any(item => item.Phase == ComponentPhase.NeedsAttention))
                    throw new InvalidOperationException("Updated DjGoo failed its startup health check.");
            }
            catch (Exception ex) when (ex is TimeoutException or IOException) { }
            await Task.Delay(1000);
        }
        throw new TimeoutException("Updated DjGoo did not become healthy; the previous version was restored.");
    }

    private string PipeName() => $"DjGoo.Host.{_paths.InstanceIdentity()}";
    private string SafeProgramPath(string relative)
    {
        var root = Path.GetFullPath(_paths.ProgramRoot).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
        var path = Path.GetFullPath(Path.Combine(_paths.ProgramRoot, relative));
        if (!path.StartsWith(root, StringComparison.OrdinalIgnoreCase)) throw new InvalidDataException("Unsafe layer path.");
        return path;
    }

    private static IEnumerable<LayerIdentity> Layers(ProductManifest manifest)
    {
        yield return manifest.Application; yield return manifest.PythonRed; yield return manifest.Java;
        yield return manifest.Lavalink; yield return manifest.WebRtc;
        if (manifest.Speech is not null) yield return manifest.Speech;
    }

    private static bool Same(LayerIdentity left, LayerIdentity right) =>
        left.Generation == right.Generation && left.Sha256 == right.Sha256 && left.Location == right.Location;

    private static async Task<string> ReadTextAsync(string location)
    {
        if (Uri.TryCreate(location, UriKind.Absolute, out var uri) && uri.Scheme is "http" or "https")
            return await new HttpClient().GetStringAsync(uri);
        return await File.ReadAllTextAsync(Path.GetFullPath(location));
    }

    private static async Task DownloadAsync(string location, string destination)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(destination)!);
        var temporary = destination + ".part";
        if (Uri.TryCreate(location, UriKind.Absolute, out var uri) && uri.Scheme is "http" or "https")
        {
            await using var output = File.Create(temporary);
            await (await new HttpClient().GetStreamAsync(uri)).CopyToAsync(output);
        }
        else File.Copy(Path.GetFullPath(location), temporary, true);
        File.Move(temporary, destination, true);
    }
}
