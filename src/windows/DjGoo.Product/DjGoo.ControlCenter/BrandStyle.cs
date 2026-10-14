using System.Reflection;

namespace DjGoo.Product.ControlCenter;

internal static class BrandStyle
{
    public static readonly Color Background = Color.FromArgb(8, 9, 29);
    public static readonly Color PanelColor = Color.FromArgb(19, 20, 55);
    public static readonly Color Surface = Color.FromArgb(28, 30, 73);
    public static readonly Color Cyan = Color.FromArgb(25, 225, 255);
    public static readonly Color Violet = Color.FromArgb(105, 61, 255);
    public static readonly Color Magenta = Color.FromArgb(236, 73, 255);
    public static readonly Color Text = Color.FromArgb(245, 247, 255);
    public static readonly Color Muted = Color.FromArgb(173, 184, 217);

    public static Image LoadMark()
    {
        using var stream = Assembly.GetExecutingAssembly().GetManifestResourceStream("DjGoo.Brand.png")
            ?? throw new InvalidOperationException("DjGoo brand image is missing.");
        using var source = Image.FromStream(stream);
        return new Bitmap(source);
    }

    public static Icon AppIcon() => Icon.ExtractAssociatedIcon(Application.ExecutablePath) ?? SystemIcons.Application;

    public static void Apply(Form form)
    {
        form.BackColor = Background;
        form.ForeColor = Text;
        form.Icon = AppIcon();
        Apply(form.Controls);
    }

    private static void Apply(Control.ControlCollection controls)
    {
        foreach (Control control in controls)
        {
            control.ForeColor = control is Label label && label.ForeColor == Color.DimGray ? Muted : Text;
            switch (control)
            {
                case Button button:
                    button.BackColor = Surface;
                    button.FlatStyle = FlatStyle.Flat;
                    button.FlatAppearance.BorderColor = Violet;
                    button.FlatAppearance.MouseOverBackColor = Color.FromArgb(44, 45, 103);
                    button.UseVisualStyleBackColor = false;
                    break;
                case TextBox textBox when !textBox.ReadOnly:
                    textBox.BackColor = PanelColor;
                    textBox.ForeColor = Text;
                    textBox.BorderStyle = BorderStyle.FixedSingle;
                    break;
                case ComboBox comboBox:
                    comboBox.BackColor = PanelColor;
                    comboBox.ForeColor = Text;
                    break;
                case TableLayoutPanel or FlowLayoutPanel or Panel:
                    control.BackColor = Background;
                    break;
            }
            if (control.HasChildren) Apply(control.Controls);
        }
    }
}
