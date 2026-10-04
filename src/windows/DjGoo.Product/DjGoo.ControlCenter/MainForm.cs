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
    private readonly TextBox _activity = new()
    {
        Dock = DockStyle.Fill,
        Multiline = true,
        ReadOnly = true,
        ScrollBars = ScrollBars.Vertical,
        Font = new Font("Consolas", 9),
        BackColor = Color.FromArgb(20, 24, 30),
        ForeColor = Color.Gainsboro,
        BorderStyle = BorderStyle.FixedSingle,
    };
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
        Width = 820;
        Height = 560;
        MinimumSize = new Size(720, 500);
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
        var body = new TableLayoutPanel { Dock = DockStyle.Fill, Padding = new Padding(24), RowCount = 7, ColumnCount = 1 };
        body.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        body.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        body.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        body.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        body.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        body.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        body.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        body.Controls.Add(_state);
        body.Controls.Add(_detail);
        var services = new Label
        {
            AutoSize = true,
            Margin = new Padding(0, 22, 0, 0),
            Text = "Music, web remote, and local voice are managed in the background."
        };
        body.Controls.Add(services);
        var actions = new FlowLayoutPanel { AutoSize = true, Dock = DockStyle.Fill, FlowDirection = FlowDirection.LeftToRight, Margin = new Padding(0, 16, 0, 0) };
        actions.Controls.Add(Button("Start", async () => await CommandAsync("start")));
        actions.Controls.Add(Button("Stop", async () => await CommandAsync("stop")));
        actions.Controls.Add(Button("Restart", async () => await CommandAsync("restart")));
        actions.Controls.Add(Button("Open web", () => Open("https://127.0.0.1:8765/")));
        body.Controls.Add(actions);

        var manage = new FlowLayoutPanel { AutoSize = true, Dock = DockStyle.Fill, FlowDirection = FlowDirection.LeftToRight, Margin = new Padding(0, 10, 0, 0) };
        manage.Controls.Add(Button("Connect Discord", ConfigureDiscordAsync));
        manage.Controls.Add(Button("Settings", OpenSettingsAsync));
        manage.Controls.Add(Button("Check for updates", () => RunUpdater("check")));
        manage.Controls.Add(Button("Repair", () => RunUpdater("repair")));
        manage.Controls.Add(Button("Open logs", OpenLogs));
        body.Controls.Add(manage);

        body.Controls.Add(new Label { AutoSize = true, Font = new Font("Segoe UI", 10, FontStyle.Bold), Margin = new Padding(0, 16, 0, 5), Text = "Activity" });
        body.Controls.Add(_activity);
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
            RefreshActivity();
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
        OpenFolder(_paths.Logs);
    }

    private static void OpenFolder(string path)
    {
        Directory.CreateDirectory(path);
        try
        {
            Process.Start(new ProcessStartInfo("explorer.exe", $"/e,\"{path}\"")
            {
                UseShellExecute = false,
                CreateNoWindow = true,
            });
        }
        catch
        {
            Open(path);
        }
    }

    private async Task ConfigureDiscordAsync()
    {
        var wasRunning = false;
        try
        {
            var response = await _client.SendAsync("status", 1500);
            wasRunning = response.Status?.DesiredRunning == true;
            if (wasRunning) await _client.SendAsync("stop", 10000);
            using var setup = new FirstRunForm(_paths);
            var saved = setup.ShowDialog(this) == DialogResult.OK;
            if (saved || wasRunning) await _client.SendAsync("start", 10000);
            await RefreshStatusAsync();
        }
        catch (Exception ex)
        {
            SetState("Needs attention", ex.Message);
        }
    }

    private async Task OpenSettingsAsync()
    {
        using var settings = new SettingsForm(_paths);
        if (settings.ShowDialog(this) != DialogResult.OK) return;
        try
        {
            await _client.SendAsync("restart", 15000);
            await RefreshStatusAsync();
        }
        catch (Exception ex)
        {
            SetState("Needs attention", ex.Message);
        }
    }

    private void RefreshActivity()
    {
        try
        {
            if (!File.Exists(_paths.HostLog)) { _activity.Text = "No activity has been recorded yet."; return; }
            var lines = File.ReadLines(_paths.HostLog).TakeLast(16);
            _activity.Lines = lines.ToArray();
            _activity.SelectionStart = _activity.TextLength;
            _activity.ScrollToCaret();
        }
        catch (IOException) { }
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
