using System.Buffers.Binary;
using System.Security.Cryptography;
using System.Text;

namespace DjGoo.Product;

public static class LayerVerifier
{
    public static void Verify(string root, LayerIdentity expected)
    {
        if (!Directory.Exists(root))
            throw new InvalidOperationException($"The {expected.Artifact} layer is missing.");
        using var hash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
        long total = 0;
        var files = Directory.EnumerateFiles(root, "*", SearchOption.AllDirectories)
            .OrderBy(path => Path.GetRelativePath(root, path).Replace('\\', '/').ToLowerInvariant(), StringComparer.Ordinal)
            .ToArray();
        Span<byte> length = stackalloc byte[8];
        foreach (var path in files)
        {
            var relative = Path.GetRelativePath(root, path).Replace('\\', '/');
            var name = Encoding.UTF8.GetBytes(relative);
            BinaryPrimitives.WriteInt32LittleEndian(length[..4], name.Length);
            hash.AppendData(length[..4]);
            hash.AppendData(name);
            var size = new FileInfo(path).Length;
            BinaryPrimitives.WriteInt64LittleEndian(length, size);
            hash.AppendData(length);
            using var stream = File.OpenRead(path);
            var buffer = new byte[1024 * 1024];
            int read;
            while ((read = stream.Read(buffer)) > 0) hash.AppendData(buffer, 0, read);
            total += size;
        }
        var actual = Convert.ToHexString(hash.GetHashAndReset()).ToLowerInvariant();
        if (total != expected.Size || !actual.Equals(expected.Sha256, StringComparison.Ordinal))
            throw new InvalidOperationException($"The {expected.Artifact} layer is damaged " +
                $"(expected {expected.Size}/{expected.Sha256}, actual {total}/{actual}). Run DjGoo-Setup.exe to repair it.");
    }

}
