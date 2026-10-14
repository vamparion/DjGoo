using DjGoo.Product;

namespace DjGoo.Product.Updater;

internal static class Program
{
    [STAThread]
    private static int Main(string[] args)
    {
        ApplicationConfiguration.Initialize();
        var command = args.FirstOrDefault()?.Trim().ToLowerInvariant() ?? "check";
        var paths = new ProductPaths();
        paths.EnsureDataDirectories();
        var quiet = command.EndsWith("-quiet", StringComparison.Ordinal) ||
                    Environment.GetEnvironmentVariable("DJGOO_UPDATER_QUIET") == "1";
        try
        {
            if (quiet) File.AppendAllText(Path.Combine(paths.Logs, "updater.log"),
                $"{DateTimeOffset.Now:O} start command={command} arguments={args.Length}\n");
            paths.EnsureProductionMutationAllowed(command);
            return command switch
            {
                "check" => Check(paths, args.Skip(1).FirstOrDefault()),
                "apply" => Apply(paths, args.Skip(1).FirstOrDefault()),
                "apply-quiet" => Apply(paths, args.Skip(1).FirstOrDefault(), false),
                "repair" => Repair(paths),
                "repair-quiet" => Repair(paths, false),
                "exit" => ExitHost(paths),
                _ => throw new InvalidOperationException("Unknown updater command."),
            };
        }
        catch (Exception ex)
        {
            if (quiet)
            {
                paths.EnsureDataDirectories();
                File.AppendAllText(Path.Combine(paths.Logs, "updater.log"),
                    $"{DateTimeOffset.Now:O} {ex}\n");
            }
            else MessageBox.Show(ex.Message, "DjGoo", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
    }

    private static int Check(ProductPaths paths, string? suppliedFeed)
    {
        var feed = suppliedFeed ?? Path.Combine(paths.Config, "update-feed.json");
        if (suppliedFeed is null && !File.Exists(feed))
        {
            MessageBox.Show("DjGoo is up to date.", "DjGoo", MessageBoxButtons.OK, MessageBoxIcon.Information);
            return 0;
        }
        if (MessageBox.Show("A verified DjGoo update is available. Install it now?", "DjGoo Update",
                MessageBoxButtons.YesNo, MessageBoxIcon.Information) != DialogResult.Yes) return 0;
        return Apply(paths, feed);
    }

    private static int Apply(ProductPaths paths, string? feed, bool notify = true)
    {
        if (string.IsNullOrWhiteSpace(feed)) throw new InvalidOperationException("A signed update feed is required.");
        var changed = new UpdateEngine(paths).ApplyAsync(feed).GetAwaiter().GetResult();
        if (notify) MessageBox.Show(changed ? "DjGoo was updated successfully." : "DjGoo is already up to date.",
            "DjGoo Update", MessageBoxButtons.OK, MessageBoxIcon.Information);
        return 0;
    }

    private static int Repair(ProductPaths paths, bool notify = true)
    {
        var product = new InstalledProduct(paths);
        var layers = new[]
        {
            product.Manifest.Application, product.Manifest.PythonRed, product.Manifest.Java,
            product.Manifest.Lavalink, product.Manifest.WebRtc,
        };
        foreach (var layer in layers)
            LayerVerifier.Verify(product.Layer(layer), layer);
        if (notify) MessageBox.Show("DjGoo installation verification completed successfully. User data was not changed.",
            "DjGoo Repair", MessageBoxButtons.OK, MessageBoxIcon.Information);
        return 0;
    }

    private static int ExitHost(ProductPaths paths)
    {
        try { EventWaitHandle.OpenExisting($"Local\\DjGoo.ControlCenter.Exit.{paths.InstanceIdentity()}").Set(); }
        catch { }
        var pipe = $"DjGoo.Host.{paths.InstanceIdentity()}";
        try { new HostPipeClient(pipe).SendAsync("exit", 10000).GetAwaiter().GetResult(); }
        catch { }
        return 0;
    }
}
