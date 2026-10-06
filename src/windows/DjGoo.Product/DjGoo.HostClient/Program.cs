using System.Text.Json;
using DjGoo.Product;

if (args.Length < 2)
{
    Console.Error.WriteLine("Usage: DjGoo.HostClient.exe <pipe-name> <command>");
    return 2;
}

try
{
    var response = await new HostPipeClient(args[0]).SendAsync(args[1]);
    Console.WriteLine(JsonSerializer.Serialize(response));
    return response.Ok ? 0 : 1;
}
catch (Exception ex)
{
    Console.Error.WriteLine(ex.Message);
    return 3;
}
