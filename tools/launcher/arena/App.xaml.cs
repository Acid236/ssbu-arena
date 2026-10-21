// SPDX-License-Identifier: GPL-3.0-or-later
using System;
using System.Globalization;
using System.Windows;
using System.Windows.Data;

namespace Arena
{
    public partial class App : Application { }

    /// <summary>a length times the converter parameter (the hero art: a share of the card's width)</summary>
    public sealed class Scale : IValueConverter
    {
        public static readonly Scale Instance = new Scale();
        public object Convert(object v, Type t, object p, CultureInfo c)
        {
            return (v is double d ? d : 0) * double.Parse((string)p, CultureInfo.InvariantCulture);
        }
        public object ConvertBack(object v, Type t, object p, CultureInfo c) { throw new NotSupportedException(); }
    }
}
