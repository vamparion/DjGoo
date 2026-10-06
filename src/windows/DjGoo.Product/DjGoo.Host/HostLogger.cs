namespace DjGoo.Product.Host;

internal sealed class HostLogger
{
    private readonly string _path;
    private readonly object _gate = new();
    public HostLogger(string path) { _path = path; Directory.CreateDirectory(Path.GetDirectoryName(path)!); }

    public void Write(string message)
    {
        lock (_gate)
        {
            var line = $"{DateTimeOffset.Now:O} {message}{Environment.NewLine}";
            for (var attempt = 0; attempt < 3; attempt++)
            {
                try
                {
                    using var stream = new FileStream(
                        _path,
                        FileMode.Append,
                        FileAccess.Write,
                        FileShare.ReadWrite | FileShare.Delete);
                    using var writer = new StreamWriter(stream);
                    writer.Write(line);
                    return;
                }
                catch (IOException) when (attempt < 2)
                {
                    Thread.Sleep(20 * (attempt + 1));
                }
                catch (IOException)
                {
                    return;
                }
                catch (UnauthorizedAccessException)
                {
                    return;
                }
            }
        }
    }
}
