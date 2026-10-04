using DjGoo.Product;

namespace DjGoo.Product.ControlCenter;

internal sealed class SettingsForm : Form
{
    private readonly ProductPaths _paths;
    private readonly TextBox _token = new() { Dock = DockStyle.Fill, UseSystemPasswordChar = true };
    private readonly TextBox _prefix = new() { Width = 90 };
    private readonly ComboBox _locale = new() { Width = 160, DropDownStyle = ComboBoxStyle.DropDown };
    private readonly TextBox _description = new() { Dock = DockStyle.Fill, Multiline = true, Height = 64 };
    private readonly CheckBox _embeds = new() { AutoSize = true, Text = "Use rich embeds for bot responses" };
    private readonly CheckBox _fuzzy = new() { AutoSize = true, Text = "Suggest similar commands when a command is mistyped" };
    private readonly CheckBox _buttons = new() { AutoSize = true, Text = "Show interactive buttons in Discord" };
    private readonly CheckBox _publicInvite = new() { AutoSize = true, Text = "Allow the bot's invite link to be shared publicly" };

    public SettingsForm(ProductPaths paths)
    {
        _paths = paths;
        Text = "DjGoo Settings";
        Width = 610;
        Height = 520;
        MinimumSize = new Size(560, 480);
        StartPosition = FormStartPosition.CenterParent;
        Font = new Font("Segoe UI", 10);
        FormBorderStyle = FormBorderStyle.Sizable;
        MaximizeBox = false;
        BuildUi();
        LoadSettings();
    }

    private void BuildUi()
    {
        var body = new TableLayoutPanel { Dock = DockStyle.Fill, Padding = new Padding(22), ColumnCount = 1, RowCount = 13 };
        body.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        body.Controls.Add(new Label { AutoSize = true, Font = new Font("Segoe UI", 16, FontStyle.Bold), Text = "Settings" });
        body.Controls.Add(Label("Discord bot token"));
        body.Controls.Add(_token);
        body.Controls.Add(new Label { AutoSize = true, ForeColor = Color.DimGray, Text = "Leave blank to keep the current token." });

        var commandRow = new FlowLayoutPanel { AutoSize = true, Dock = DockStyle.Fill, WrapContents = false, Margin = new Padding(0, 12, 0, 0) };
        commandRow.Controls.Add(new Label { AutoSize = true, Margin = new Padding(0, 7, 8, 0), Text = "Command prefix" });
        commandRow.Controls.Add(_prefix);
        commandRow.Controls.Add(new Label { AutoSize = true, Margin = new Padding(24, 7, 8, 0), Text = "Language" });
        _locale.Items.AddRange(new object[] { "en-US", "en-GB", "de-DE", "es-ES", "fr-FR", "it-IT", "ja-JP", "ko-KR", "pt-BR" });
        commandRow.Controls.Add(_locale);
        body.Controls.Add(commandRow);

        body.Controls.Add(Label("Bot description"));
        body.Controls.Add(_description);
        body.Controls.Add(_embeds);
        body.Controls.Add(_fuzzy);
        body.Controls.Add(_buttons);
        body.Controls.Add(_publicInvite);
        body.Controls.Add(new Label { AutoSize = true, ForeColor = Color.DimGray, Margin = new Padding(0, 12, 0, 0), Text = "Saving restarts DjGoo so the new settings take effect." });

        var actions = new FlowLayoutPanel { AutoSize = true, Dock = DockStyle.Fill, FlowDirection = FlowDirection.RightToLeft, Margin = new Padding(0, 16, 0, 0) };
        var save = new Button { Text = "Save", AutoSize = true, MinimumSize = new Size(92, 34) };
        save.Click += (_, _) => SaveSettings();
        var cancel = new Button { Text = "Cancel", AutoSize = true, MinimumSize = new Size(92, 34), DialogResult = DialogResult.Cancel };
        actions.Controls.Add(save);
        actions.Controls.Add(cancel);
        body.Controls.Add(actions);
        Controls.Add(body);
        AcceptButton = save;
        CancelButton = cancel;
    }

    private static Label Label(string text) => new() { AutoSize = true, Margin = new Padding(0, 12, 0, 3), Text = text };

    private void LoadSettings()
    {
        var settings = ProductSettingsStore.Load(_paths);
        _prefix.Text = settings.Prefix;
        _locale.Text = settings.Locale;
        _description.Text = settings.Description;
        _embeds.Checked = settings.Embeds;
        _fuzzy.Checked = settings.Fuzzy;
        _buttons.Checked = settings.UseButtons;
        _publicInvite.Checked = settings.InvitePublic;
    }

    private void SaveSettings()
    {
        try
        {
            var current = ProductSettingsStore.Load(_paths);
            var settings = current with
            {
                Prefix = _prefix.Text,
                Locale = _locale.Text,
                Embeds = _embeds.Checked,
                Fuzzy = _fuzzy.Checked,
                UseButtons = _buttons.Checked,
                InvitePublic = _publicInvite.Checked,
                Description = _description.Text,
            };
            ProductSettingsStore.Save(_paths, settings, _token.Text);
            DialogResult = DialogResult.OK;
            Close();
        }
        catch (Exception ex) when (ex is ArgumentException or IOException)
        {
            MessageBox.Show(ex.Message, "DjGoo Settings", MessageBoxButtons.OK, MessageBoxIcon.Warning);
        }
    }
}
