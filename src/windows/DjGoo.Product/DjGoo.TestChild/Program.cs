if (args.Contains("--crash")) return 23;
var eventIndex = Array.FindIndex(args, value => value == "--shutdown-event");
if (eventIndex >= 0 && eventIndex + 1 < args.Length)
{
    using var shutdown = EventWaitHandle.OpenExisting(args[eventIndex + 1]);
    shutdown.WaitOne();
    return 0;
}
using var wait = new ManualResetEventSlim(false);
wait.Wait();
return 0;
