using System.Diagnostics;
using System.Security.Principal;
using DjGoo.Product;
using DjGoo.Product.ControlCenter;

internal static class Program
{
    [STAThread]
    private static void Main()
    {
        ApplicationConfiguration.Initialize();
        var paths = new ProductPaths();
        paths.EnsureDataDirectories();
        if (!FirstRunForm.IsConfigured(paths))
        {
            using var setup = new FirstRunForm(paths);
            if (setup.ShowDialog() != DialogResult.OK) return;
        }
        var identity = paths.InstanceIdentity();
        var user = WindowsIdentity.GetCurrent().User?.Value ?? Environment.UserName;
        var mutexName = $"Local\\DjGoo.ControlCenter.{user.Replace('\\', '_')}.{identity}";
        var activateName = $"Local\\DjGoo.ControlCenter.Activate.{identity}";
        var exitName = $"Local\\DjGoo.ControlCenter.Exit.{identity}";
        using var mutex = new Mutex(true, mutexName, out var ownsMutex);
        if (!ownsMutex)
        {
            try { EventWaitHandle.OpenExisting(activateName).Set(); } catch (WaitHandleCannotBeOpenedException) { }
            return;
        }

        using var activate = new EventWaitHandle(false, EventResetMode.AutoReset, activateName);
        using var exit = new EventWaitHandle(false, EventResetMode.AutoReset, exitName);
        var pipeName = $"DjGoo.Host.{identity}";
        EnsureHostAsync(paths, pipeName).GetAwaiter().GetResult();
        using var form = new MainForm(paths, pipeName, activate, exit, () => EnsureHostAsync(paths, pipeName));
        Application.Run(form);
    }

    internal static async Task EnsureHostAsync(ProductPaths paths, string pipeName)
    {
        var client = new HostPipeClient(pipeName);
        try { await client.SendAsync("hello", 750); }
        catch
        {
            var host = Path.Combine(paths.ProgramRoot, "DjGoo.Host.exe");
            Process.Start(new ProcessStartInfo(host)
            {
                UseShellExecute = false,
                CreateNoWindow = true,
                WorkingDirectory = paths.ProgramRoot,
            });
            var deadline = DateTime.UtcNow.AddSeconds(15);
            while (DateTime.UtcNow < deadline)
            {
                try { await client.SendAsync("hello", 500); break; }
                catch { await Task.Delay(150); }
            }
        }
        await client.SendAsync("start", 5000);
    }
}
