using System.Globalization;
using System.Windows;
using System.Windows.Data;

namespace StarLinkPOC.Converters
{
    /// <summary>
    /// Multi-purpose → Visibility converter.
    /// - bool:   true  → Visible,   false → Collapsed
    /// - string: non-empty → Visible, empty/null → Collapsed
    /// Use ConverterParameter="Invert" to flip the logic.
    /// </summary>
    [ValueConversion(typeof(object), typeof(Visibility))]
    public class BoolToVisibilityConverter : IValueConverter
    {
        public object Convert(object value, Type targetType, object parameter, CultureInfo culture)
        {
            bool flag = value switch
            {
                bool b   => b,
                string s => !string.IsNullOrEmpty(s),
                null     => false,
                _        => true
            };

            bool invert = parameter is string p &&
                          p.Equals("Invert", StringComparison.OrdinalIgnoreCase);
            if (invert) flag = !flag;

            return flag ? Visibility.Visible : Visibility.Collapsed;
        }

        public object ConvertBack(object value, Type targetType, object parameter, CultureInfo culture)
            => value is Visibility v && v == Visibility.Visible;
    }
}
