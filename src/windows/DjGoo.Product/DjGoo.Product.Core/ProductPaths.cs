using System.Security.Cryptography;
using System.Text;

namespace DjGoo.Product;

public sealed class ProductPaths
{
    public ProductPaths(string? programRoot = null, string? dataRoot = null)
    {
        var local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        ProgramRoot = Path.GetFullPath(programRoot ?? Path.Combine(local, "Programs", "DjGoo"));
        DataRoot = Path.GetFullPath(dataRoot ?? Path.Combine(local, "DjGoo"));
        if (StringComparer.OrdinalIgnoreCase.Equals(ProgramRoot, DataRoot) ||
            IsInside(ProgramRoot, DataRoot) || IsInside(DataRoot, ProgramRoot))
            throw new InvalidOperationException("DjGoo program and data roots must be separate.");
    }

    public string ProgramRoot { get; }
    public string DataRoot { get; }
    public string Applications => Path.Combine(ProgramRoot, "app");
    public string RuntimeLayers => Path.Combine(ProgramRoot, "layers");
    public string Config => Path.Combine(DataRoot, "config");
    public string Credentials => Path.Combine(DataRoot, "credentials");
    public string Pairings => Path.Combine(DataRoot, "pairings");
    public string Logs => Path.Combine(DataRoot, "logs");
    public string Health => Path.Combine(DataRoot, "health");
    public string Downloads => Path.Combine(DataRoot, "downloads");
    public string Staging => Path.Combine(DataRoot, "staging");
    public string Rollback => Path.Combine(DataRoot, "rollback");
    public string HostLog => Path.Combine(Logs, "host.log");

    public bool IsDeveloperMode => Directory.Exists(Path.Combine(ProgramRoot, ".git")) ||
                                   File.Exists(Path.Combine(ProgramRoot, ".git"));

    public void EnsureDataDirectories()
    {
        foreach (var path in new[] { Config, Credentials, Pairings, Logs, Health, Downloads, Staging, Rollback })
            Directory.CreateDirectory(path);
    }

    public void EnsureProductionMutationAllowed(string operation)
    {
        if (IsDeveloperMode)
            throw new InvalidOperationException(
                $"Developer Mode checkout cannot be modified by production {operation}.");
    }

    public string InstanceIdentity()
    {
        var bytes = SHA256.HashData(Encoding.UTF8.GetBytes(ProgramRoot.ToUpperInvariant()));
        return Convert.ToHexString(bytes.AsSpan(0, 12)).ToLowerInvariant();
    }

    private static bool IsInside(string parent, string candidate)
    {
        var relative = Path.GetRelativePath(parent, candidate);
        return relative != "." && !Path.IsPathRooted(relative) &&
               !relative.Equals("..", StringComparison.Ordinal) &&
               !relative.StartsWith(".." + Path.DirectorySeparatorChar, StringComparison.Ordinal);
    }
}
