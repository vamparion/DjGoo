namespace DjGoo.Product.Host;

internal sealed class HostLogger
{
    private readonly string _path;
    private readonly object _gate = new();
    public HostLogger(string path) { _path = path; Directory.CreateDirectory(Path.GetDirectoryName(path)!); }

    public void Write(string message)
    {
        lock (_gate)
            File.AppendAllText(_path, $"{DateTimeOffset.Now:O} {message}{Environment.NewLine}");
    }
}
