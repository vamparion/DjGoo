using System.Text.Json;
using DjGoo.Product;

namespace DjGoo.Product.ControlCenter;

internal sealed class FirstRunForm : Form
{
    private readonly ProductPaths _paths;
    private readonly TextBox _token = new() { Width = 420, UseSystemPasswordChar = true };
    private readonly TextBox _prefix = new() { Width = 80, Text = "!" };

    public FirstRunForm(ProductPaths paths)
    {
        _paths = paths;
        Text = "Set up DjGoo";
        Width = 520;
        Height = 290;
        FormBorderStyle = FormBorderStyle.FixedDialog;
        MaximizeBox = false;
        MinimizeBox = false;
        StartPosition = FormStartPosition.CenterScreen;
        Font = new Font("Segoe UI", 10);

        var layout = new TableLayoutPanel { Dock = DockStyle.Fill, Padding = new Padding(22), ColumnCount = 1, RowCount = 7 };
        layout.Controls.Add(new Label { AutoSize = true, Font = new Font("Segoe UI", 16, FontStyle.Bold), Text = "Connect your Discord bot" });
        layout.Controls.Add(new Label { AutoSize = true, Margin = new Padding(0, 8, 0, 2), Text = "Bot token" });
        layout.Controls.Add(_token);
        layout.Controls.Add(new Label { AutoSize = true, Margin = new Padding(0, 10, 0, 2), Text = "Command prefix" });
        layout.Controls.Add(_prefix);
        layout.Controls.Add(new Label { AutoSize = true, ForeColor = Color.DimGray, Margin = new Padding(0, 10, 0, 4), Text = IsConfigured(paths) ? "Leave the token blank to keep the existing token." : "Stored only in your private DjGoo data folder." });
        var continueButton = new Button { Text = "Continue", AutoSize = true, MinimumSize = new Size(100, 34) };
        continueButton.Click += (_, _) => Save();
        layout.Controls.Add(continueButton);
        Controls.Add(layout);
        BrandStyle.Apply(this);
        AcceptButton = continueButton;
    }

    public static bool IsConfigured(ProductPaths paths)
    {
        return ProductSettingsStore.Load(paths).HasToken;
    }

    private void Save()
    {
        var token = _token.Text.Trim();
        var prefix = _prefix.Text.Trim();
        var configured = IsConfigured(_paths);
        if ((!configured && token.Length < 20) || (token.Length > 0 && token.Length < 20) || string.IsNullOrWhiteSpace(prefix))
        {
            MessageBox.Show("Enter a Discord bot token and command prefix.", "DjGoo", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return;
        }
        var settings = ProductSettingsStore.Load(_paths) with { Prefix = prefix };
        ProductSettingsStore.Save(_paths, settings, token);
        DialogResult = DialogResult.OK;
        Close();
    }
}
