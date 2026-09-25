using System.Diagnostics;
using DjGoo.Product;

namespace DjGoo.Product.ControlCenter;

internal sealed class MainForm : Form
{
    private readonly ProductPaths _paths;
    private readonly HostPipeClient _client;
    private readonly NotifyIcon _tray;
    private readonly Label _state = new() { AutoSize = true, Font = new Font("Segoe UI", 18, FontStyle.Bold), Text = "Starting" };
    private readonly Label _detail = new() { AutoSize = true, ForeColor = Color.DimGray, Text = "Connecting to DjGoo Host" };
    private readonly System.Windows.Forms.Timer _refresh = new() { Interval = 1500 };
    private readonly RegisteredWaitHandle _activateWait;
    private readonly RegisteredWaitHandle _exitWait;
    private readonly Func<Task> _ensureHost;
    private bool _reconnecting;
    private bool _exiting;

    public MainForm(ProductPaths paths, string pipeName, EventWaitHandle activate, EventWaitHandle exit, Func<Task> ensureHost)
    {
        _paths = paths;
        _client = new HostPipeClient(pipeName);
        _ensureHost = ensureHost;
        Text = "DjGoo";
        Width = 560;
        Height = 330;
        MinimumSize = new Size(500, 300);
        StartPosition = FormStartPosition.CenterScreen;
        Font = new Font("Segoe UI", 10);
        BuildUi();
        _tray = BuildTray();
        _activateWait = ThreadPool.RegisterWaitForSingleObject(activate, (_, _) => BeginInvoke(ShowCenter), null, -1, false);
        _exitWait = ThreadPool.RegisterWaitForSingleObject(exit, (_, _) => BeginInvoke(ExitControlCenter), null, -1, false);
        _refresh.Tick += async (_, _) => await RefreshStatusAsync();
        Shown += async (_, _) => { _refresh.Start(); await RefreshStatusAsync(); };
        FormClosing += (_, eventArgs) =>
        {
            if (_exiting) return;
            eventArgs.Cancel = true;
            Hide();
        };
    }

    private void BuildUi()
    {
        var body = new TableLayoutPanel { Dock = DockStyle.Fill, Padding = new Padding(24), RowCount = 4, ColumnCount = 1 };
        body.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        body.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        body.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        body.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        body.Controls.Add(_state);
        body.Controls.Add(_detail);
        var services = new Label
        {
            AutoSize = true,
            Margin = new Padding(0, 22, 0, 0),
            Text = "Music, web remote, and local voice are managed in the background."
        };
        body.Controls.Add(services);
        var actions = new FlowLayoutPanel { AutoSize = true, Dock = DockStyle.Fill, FlowDirection = FlowDirection.LeftToRight };
        actions.Controls.Add(Button("Start", async () => await CommandAsync("start")));
        actions.Controls.Add(Button("Stop", async () => await CommandAsync("stop")));
        actions.Controls.Add(Button("Restart", async () => await CommandAsync("restart")));
        actions.Controls.Add(Button("Open web", () => Open("https://127.0.0.1:8765/")));
        actions.Controls.Add(Button("Open logs", OpenLogs));
        body.Controls.Add(actions);
        Controls.Add(body);
    }

    private NotifyIcon BuildTray()
    {
        var menu = new ContextMenuStrip();
        menu.Items.Add("Open DjGoo", null, (_, _) => ShowCenter());
        menu.Items.Add(new ToolStripSeparator());
        menu.Items.Add("Start", null, async (_, _) => await CommandAsync("start"));
        menu.Items.Add("Stop", null, async (_, _) => await CommandAsync("stop"));
        menu.Items.Add("Restart", null, async (_, _) => await CommandAsync("restart"));
        menu.Items.Add(new ToolStripSeparator());
        menu.Items.Add("Check for updates", null, (_, _) => RunUpdater("check"));
        menu.Items.Add("Repair", null, (_, _) => RunUpdater("repair"));
        menu.Items.Add("Open logs", null, (_, _) => OpenLogs());
        menu.Items.Add(new ToolStripSeparator());
        menu.Items.Add("Exit DjGoo", null, async (_, _) => await ExitAsync());
        var tray = new NotifyIcon
        {
            Text = "DjGoo",
            Icon = SystemIcons.Application,
            ContextMenuStrip = menu,
            Visible = true,
        };
        tray.DoubleClick += (_, _) => ShowCenter();
        return tray;
    }

    private static Button Button(string text, Func<Task> action)
    {
        var button = new Button { Text = text, AutoSize = true, MinimumSize = new Size(88, 34), Margin = new Padding(0, 0, 8, 0) };
        button.Click += async (_, _) => await action();
        return button;
    }

    private static Button Button(string text, Action action) => Button(text, () => { action(); return Task.CompletedTask; });

    private async Task CommandAsync(string command)
    {
        try { await _client.SendAsync(command, 10000); await RefreshStatusAsync(); }
        catch (Exception ex)
        {
            SetState("Starting", "Reconnecting to DjGoo Host");
            if (_reconnecting) return;
            _reconnecting = true;
            try { await _ensureHost(); }
            catch { SetState("Needs attention", ex.Message); }
            finally { _reconnecting = false; }
        }
    }

    private async Task RefreshStatusAsync()
    {
        try
        {
            var response = await _client.SendAsync("status", 1500);
            var status = response.Status!;
            var required = status.Components.Where(item => item.Kind != ProductComponentKind.LocalVoice).ToArray();
            var label = !status.DesiredRunning ? "Stopped"
                : required.All(item => item.Phase == ComponentPhase.Running) ? "Running"
                : required.Any(item => item.Phase == ComponentPhase.NeedsAttention) ? "Needs attention"
                : required.Any(item => item.Phase == ComponentPhase.Recovering) ? "Recovering" : "Starting";
            var details = string.Join("  |  ", status.Components.Select(item => $"{Display(item.Kind)}: {Simple(item.Phase)}"));
            SetState(label, details);
        }
        catch (Exception ex) { SetState("Needs attention", ex.Message); }
    }

    private void SetState(string state, string detail)
    {
        _state.Text = state;
        _detail.Text = detail;
        _tray.Text = $"DjGoo - {state}"[..Math.Min(63, $"DjGoo - {state}".Length)];
    }

    private static string Display(ProductComponentKind kind) => kind switch
    {
        ProductComponentKind.Red => "Music",
        ProductComponentKind.Lavalink => "Audio",
        ProductComponentKind.WebRemote => "Web",
        ProductComponentKind.LocalVoice => "Voice",
        _ => kind.ToString(),
    };

    private static string Simple(ComponentPhase phase) => phase switch
    {
        ComponentPhase.NeedsAttention => "Needs attention",
        _ => phase.ToString(),
    };

    private void ShowCenter() { Show(); WindowState = FormWindowState.Normal; Activate(); }
    private void OpenLogs()
    {
        _paths.EnsureDataDirectories();
        Open(_paths.Logs);
    }
    private static void Open(string target) => Process.Start(new ProcessStartInfo(target) { UseShellExecute = true });
    private void RunUpdater(string command) => Process.Start(new ProcessStartInfo(Path.Combine(_paths.ProgramRoot, "DjGoo.Updater.exe"), command) { UseShellExecute = true });

    private async Task ExitAsync()
    {
        _exiting = true;
        _refresh.Stop();
        try { await _client.SendAsync("exit", 10000); } catch { }
        _tray.Visible = false;
        Close();
        Application.Exit();
    }

    private void ExitControlCenter()
    {
        _exiting = true;
        _refresh.Stop();
        _tray.Visible = false;
        Close();
        Application.Exit();
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing) { _activateWait.Unregister(null); _exitWait.Unregister(null); _refresh.Dispose(); _tray.Dispose(); }
        base.Dispose(disposing);
    }
}
