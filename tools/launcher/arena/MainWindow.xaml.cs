// SPDX-License-Identifier: GPL-3.0-or-later
// SSBU Arena launcher window: home (play, player, setup), replays, community, settings. The work is in Core.cs.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Shapes;
using System.Windows.Threading;

namespace Arena
{
    public partial class MainWindow : Window
    {
        List<Check> checks;                 // last game files check (null while it runs)
        List<string> missingCodecs = new List<string>();
        List<Pad> pads = new List<Pad>();   // the game's own list (--pad-list)
        List<string> padGuids = new List<string>();
        int xinput;
        Process game;
        bool loading = true;                // filling the fields: their change events must not save

        public MainWindow()
        {
            InitializeComponent();
            Core.Load();
            SpaceOut(this);
            FillSettings();
            loading = false;
            RefreshPlayer();
            RefreshOnline();
            SetPadState();
            StateChanged += (s, e) => Root.Margin = WindowState == WindowState.Maximized ? new Thickness(7) : new Thickness(0);
            Closing += (s, e) => { SaveQuiet(); if (prep != null) { prepCancelled = true; try { prep.Kill(); } catch { } } };
            var poll = new DispatcherTimer { Interval = TimeSpan.FromSeconds(2) };
            poll.Tick += (s, e) => { int n = Core.XInputCount(); if (n != xinput) { xinput = n; SetPadState(); } };
            poll.Start();
            xinput = Core.XInputCount();
            Loaded += (s, e) => { RunChecks(); FindPads(); OpenFromArgs(); ResumeAccount(); CheckUpdates(); };
            Scaled.SizeChanged += (s, e) => Rescale();
            SizeChanged += (s, e) => Rescale();
        }

        // ---------------------------------------------------------------- look
        /// <summary>the page is designed at 1586 x 956 (the mockup's size under the title bar): scale it to the window,
        /// the longer side keeps the extra room</summary>
        void Rescale()
        {
            var host = (FrameworkElement)Scaled.Parent;
            double w = host.ActualWidth - Root.Margin.Left - Root.Margin.Right, h = host.ActualHeight - 36 - Root.Margin.Top - Root.Margin.Bottom;
            if (w <= 0 || h <= 0) return;
            double z = Math.Max(0.55, Math.Min(1.6, Math.Min(w / 1586, h / 956)));
            if (Math.Abs(z - Zoom.ScaleX) < 0.001) return;
            Zoom.ScaleX = Zoom.ScaleY = z;
        }

        /// <summary>letter-spaced caps (TextBlock has no letter spacing): the TextBlocks tagged "sp"</summary>
        static void SpaceOut(DependencyObject root)
        {
            foreach (var o in LogicalTreeHelper.GetChildren(root))
            {
                if (o is TextBlock t && (t.Tag as string) == "sp") t.Text = Spaced(t.Text);
                if (o is DependencyObject d) SpaceOut(d);
            }
        }

        static string Spaced(string s) { return string.Join(" ", s.Select(c => c == ' ' ? " " : c.ToString())); }

        static Brush Res(string key) { return (Brush)Application.Current.Resources[key]; }

        /// <summary>the round status mark: ok (accent, check), warn (amber, !), bad (red, x), busy (ring)</summary>
        static UIElement Mark(string kind, double size = 30)
        {
            var g = new Grid { Width = size, Height = size };
            if (kind == "busy")
            {
                g.Children.Add(new Ellipse { Stroke = Res("Line"), StrokeThickness = 2.5 });
                var arc = new Ellipse { Stroke = Res("Accent"), StrokeThickness = 2.5, StrokeDashArray = new DoubleCollection { 3, 6 }, RenderTransformOrigin = new Point(0.5, 0.5) };
                var rt = new RotateTransform();
                arc.RenderTransform = rt;
                rt.BeginAnimation(RotateTransform.AngleProperty, new System.Windows.Media.Animation.DoubleAnimation(0, 360, TimeSpan.FromSeconds(1.4)) { RepeatBehavior = System.Windows.Media.Animation.RepeatBehavior.Forever });
                g.Children.Add(arc);
                return g;
            }
            var fill = kind == "ok" ? Res("Accent") : kind == "good" ? Res("Good") : kind == "warn" ? Res("Warn") : Res("Bad");
            g.Children.Add(new Ellipse { Fill = fill });
            string geo = kind == "ok" || kind == "good" ? "IcoCheck" : kind == "warn" ? "IcoBang" : "IcoCross";
            g.Children.Add(new Path
            {
                Data = (Geometry)Application.Current.Resources[geo], Stroke = new SolidColorBrush(Color.FromRgb(6, 18, 29)), StrokeThickness = size / 11,
                StrokeStartLineCap = PenLineCap.Round, StrokeEndLineCap = PenLineCap.Round, StrokeLineJoin = PenLineJoin.Round,
                Width = size, Height = size, Stretch = Stretch.None, RenderTransform = new ScaleTransform(size / 24, size / 24)
            });
            return g;
        }

        void Status(string text, string kind)
        {
            StatusText.Text = text;
            StatusMark.Content = Mark(kind, 24);
        }

        void SetState()
        {
            if (game != null)
            {
                StateText.Text = Spaced("GAME RUNNING"); StateDot.Fill = Res("Good");
                PlayButton.IsEnabled = false; PlayText.Text = "RUNNING";
                Status("Game running", "good");
                return;
            }
            PlayButton.IsEnabled = true; PlayText.Text = "PLAY";
            if (checks == null) { StateText.Text = Spaced("CHECKING FILES"); StateDot.Fill = Res("Muted"); Status("Checking game files...", "busy"); }
            else if (checks.All(c => c.Ok)) { StateText.Text = Spaced("READY TO PLAY"); StateDot.Fill = Res("Accent"); Status("Game ready", "good"); }
            else { StateText.Text = Spaced("NEEDS ATTENTION"); StateDot.Fill = Res("Warn"); Status("The game needs attention: see Game files", "warn"); }
        }

        void RefreshPlayer()
        {
            string n = Core.Nickname.Trim();
            if (Account.SignedIn)
            {
                PlayerName.Text = Account.Me.Username.ToUpperInvariant();
                PlayerTag.Text = Spaced("ARENA#" + Account.Me.Tag.ToString("0000"));
                return;
            }
            PlayerName.Text = n == "" ? "OFFLINE" : n.ToUpperInvariant();
            PlayerTag.Text = Spaced("NOT SIGNED IN");
            UidText.Text = n == "" ? "Write a name." : "Player id (from the name): " + Core.UidFromName(n).Substring(0, 16) + "...";
        }

        void RefreshOnline()
        {
            string code = Core.Code.Trim();
            CodeBig.Text = code == "" ? "PUBLIC" : code.ToUpperInvariant();
            if (!Core.HasOnline) { NetDot.Fill = Res("Dim"); NetText.Text = "This build has no online"; }
            else if (!Core.Online) { NetDot.Fill = Res("Dim"); NetText.Text = "Offline"; }
            else
            {
                NetDot.Fill = Res("Good");
                NetText.Text = "Online" + (Core.Rollback ? " · rollback" : "") + " · code " + (code == "" ? "public" : code);
            }
            bool on = OnlineBox.IsChecked == true && Core.HasOnline;
            OnlineFields.IsEnabled = on;
            OnlineFields.Opacity = on ? 1 : 0.45;
            OnlineHelp.Text = !Core.HasOnline ? "This build of the game has no online." : !on ? "Online off: local play only."
                            : RollbackBox.IsChecked == true ? "Rollback: 1-on-1 in Local Wireless rooms, and Smash > Versus with a code." : "Local Wireless rooms through the server (the game's netcode).";
        }

        void SetPadState()
        {
            int n = Math.Max(xinput, pads.Count);
            if (n > 0)
            {
                PadSub.Text = pads.Count == 1 ? pads[0].Name : n == 1 ? "Connected" : n + " connected";
                PadMark.Content = Mark("ok");
            }
            else { PadSub.Text = "None: keyboard only"; PadMark.Content = Mark("warn"); }
        }

        // ---------------------------------------------------------------- checks and controllers
        void RunChecks()
        {
            checks = null;
            FilesSub.Text = "Checking...";
            FilesMark.Content = Mark("busy");
            SetState();
            Task.Run(() => { var r = Core.CheckFiles(out var mc); return Tuple.Create(r, mc); }).ContinueWith(t =>
            {
                checks = t.Result.Item1; missingCodecs = t.Result.Item2;
                int bad = checks.Count(c => !c.Ok);
                bool shaders = Core.CanPrepare() ? !Core.NeedsPrepare() : !Core.FirstRun();
                FilesSub.Text = bad > 0 ? bad + (bad == 1 ? " problem" : " problems") : shaders ? "Verified" : "Verified, shaders not prepared yet";
                FilesMark.Content = Mark(bad == 0 ? "ok" : "bad");
                var rows = checks.Select(c => CheckRow(c.Ok, c.Text)).ToList();
                rows.Add(CheckRow(shaders, shaders ? "Shaders prepared for this graphics card" : "Shaders not prepared yet: done before the first match (a few minutes, once)", shaders ? "ok" : "warn"));
                CheckList.ItemsSource = rows;
                SetState();
            }, TaskScheduler.FromCurrentSynchronizationContext());
        }

        static UIElement CheckRow(bool ok, string text, string kind = null)
        {
            var sp = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 5, 0, 5) };
            sp.Children.Add(Mark(kind ?? (ok ? "ok" : "bad"), 22));
            sp.Children.Add(new TextBlock { Text = text, FontSize = 15, Margin = new Thickness(14, 0, 0, 0), VerticalAlignment = VerticalAlignment.Center, TextWrapping = TextWrapping.Wrap, MaxWidth = 560 });
            return sp;
        }

        void FindPads()
        {
            if (game != null) return;
            PadsHelp.Text = "Looking for controllers...";
            Task.Run(() => Core.ListPads()).ContinueWith(t =>
            {
                pads = t.Result;
                FillPads();
                SetPadState();
            }, TaskScheduler.FromCurrentSynchronizationContext());
        }

        void FillPads()
        {
            bool was = loading;
            loading = true;
            padGuids = new List<string> { "auto", "none" };
            var names = new List<string> { "Automatic", "None" };
            foreach (var p in pads) { padGuids.Add(p.Guid); names.Add(p.Name); }
            foreach (var v in new[] { Core.Player1, Core.Player2 })
                if (!padGuids.Contains(v)) { padGuids.Add(v); names.Add("(not connected) " + v.Substring(0, Math.Min(8, v.Length))); }
            foreach (var pair in new[] { Tuple.Create(P1Box, Core.Player1), Tuple.Create(P2Box, Core.Player2) })
            {
                pair.Item1.ItemsSource = names.ToList();
                pair.Item1.SelectedIndex = padGuids.IndexOf(pair.Item2);
            }
            PadsHelp.Text = "Controllers found: " + pads.Count + ". Automatic: the first controller that connects. None: the slot stays empty.";
            loading = was;
        }

        // ---------------------------------------------------------------- settings
        void FillSettings()
        {
            NameBox.Text = Core.Nickname;
            OnlineBox.IsChecked = Core.Online;
            OnlineBox.IsEnabled = Core.HasOnline;
            CodeBox.Text = Core.Code;
            RollbackBox.IsChecked = Core.Rollback;
            PingBox.IsChecked = Core.Ping;
            ServerBox.Text = Core.Server;
            WinBox.SelectedIndex = Core.WindowMode;
            SizeBox.Text = Core.WindowSize;
            SizeBox.IsEnabled = Core.WindowMode == 0;
            AspectBox.SelectedIndex = Core.Aspect;
            KbBox.SelectedIndex = Core.Keyboard;
            FillPads();
            CompBox.IsChecked = Core.Competitive;
            CompBox.IsEnabled = Core.HasCompetitive && !Core.LightArc;
            if (Core.LightArc) CompHelp.Text = "Always on: the light archive holds only the competitive 1v1.";
            else if (!Core.HasCompetitive) CompHelp.Text = "build\\characters\\competitive is missing: python tools/competitive/make_competitive.py";
            RefreshSaves();
            RefreshDlc();
        }

        /// <summary>fields -> Core</summary>
        void ReadFields()
        {
            Core.Nickname = NameBox.Text.Trim();
            Core.Online = OnlineBox.IsChecked == true && Core.HasOnline;
            Core.Code = CodeBox.Text.Trim();
            Core.Rollback = RollbackBox.IsChecked == true;
            Core.Ping = PingBox.IsChecked == true;
            Core.Server = ServerBox.Text.Trim();
            Core.WindowMode = Math.Max(0, WinBox.SelectedIndex);
            Core.WindowSize = SizeBox.Text.Trim();
            Core.Aspect = Math.Max(0, AspectBox.SelectedIndex);
            Core.Keyboard = Math.Max(0, KbBox.SelectedIndex);
            if (P1Box.SelectedIndex >= 0) Core.Player1 = padGuids[P1Box.SelectedIndex];
            if (P2Box.SelectedIndex >= 0) Core.Player2 = padGuids[P2Box.SelectedIndex];
            Core.Competitive = CompBox.IsChecked == true;
        }

        bool SaveQuiet()
        {
            ReadFields();
            try { Core.Save(); return true; }
            catch (Exception ex) { Show("Could not save", ex.Message, null, ("OK", null, true)); return false; }
        }

        void RefreshSaves()
        {
            SavesPath.Text = Core.Saves;
            SavesState.Text = Core.HasSave() ? "A save is there." : "Empty: the game makes a new one.";
        }

        void RefreshDlc()
        {
            int n = Core.DlcCount();
            DlcText.Text = n == 0 ? "No DLC active." : n + " DLC active.";
        }

        void Field_Changed(object sender, RoutedEventArgs e)
        {
            if (loading) return;
            ReadFields();
            RefreshOnline();
        }

        void Name_Changed(object sender, TextChangedEventArgs e)
        {
            if (loading) return;
            ReadFields();
            RefreshPlayer();
        }

        void Online_Changed(object sender, RoutedEventArgs e) { Field_Changed(sender, e); }

        void Win_Changed(object sender, SelectionChangedEventArgs e)
        {
            SizeBox.IsEnabled = WinBox.SelectedIndex == 0;
            Field_Changed(sender, e);
        }

        void DefaultServer_Click(object sender, RoutedEventArgs e) { ServerBox.Text = Core.DefaultServer; }

        void FindPads_Click(object sender, RoutedEventArgs e) { FindPads(); }

        void OpenSaves_Click(object sender, RoutedEventArgs e)
        {
            System.IO.Directory.CreateDirectory(Core.Saves);
            Core.Open(Core.Saves);
        }

        static string PickFolder(string what)
        {
            using (var d = new System.Windows.Forms.FolderBrowserDialog { Description = what })
                return d.ShowDialog() == System.Windows.Forms.DialogResult.OK ? d.SelectedPath : null;
        }

        void ChangeSaves_Click(object sender, RoutedEventArgs e)
        {
            string p = PickFolder("The game's save folder");
            if (p == null) return;
            Core.Saves = p;
            RefreshSaves();
            SaveQuiet();
        }

        void Import(string from)
        {
            string msg;
            try { msg = Core.ImportSave(from); } catch (Exception ex) { msg = ex.Message; }
            RefreshSaves();
            Show("Saves", msg, null, ("OK", null, true));
        }

        void Ryujinx_Click(object sender, RoutedEventArgs e)
        {
            string f = Core.FindRyujinxSave();
            if (f != null) Import(f);
            else Show("Saves", "No Smash save found in Ryujinx (%APPDATA%\\Ryujinx\\bis\\user\\save). Use Import from folder.", null, ("OK", null, true));
        }

        void ImportFolder_Click(object sender, RoutedEventArgs e)
        {
            string p = PickFolder("The folder holding save_data (or system_data.bin): from Ryujinx, yuzu and similar, or from a console dump");
            if (p != null) Import(p);
        }

        void Dlc_Click(object sender, RoutedEventArgs e)
        {
            string p = PickFolder("The folder with the dumps of YOUR Smash DLC (files with [01006A800016Fxxx] in the name)");
            if (p == null) return;
            int n = 0;
            try { n = Core.ActivateDlc(p); } catch (Exception ex) { Show("DLC", ex.Message, null, ("OK", null, true)); return; }
            RefreshDlc();
            if (n == 0) Show("DLC", "No Smash DLC recognised from the file names.", null, ("OK", null, true));
        }

        void DlcOff_Click(object sender, RoutedEventArgs e) { Core.ClearDlc(); RefreshDlc(); }

        void Recheck_Click(object sender, RoutedEventArgs e) { RunChecks(); }

        void OpenLog_Click(object sender, RoutedEventArgs e)
        {
            if (System.IO.File.Exists(Core.GameLog)) Process.Start("notepad.exe", "\"" + Core.GameLog + "\"");
        }

        // ---------------------------------------------------------------- navigation
        void ShowPage(UIElement page)
        {
            foreach (var p in new UIElement[] { PageHome, PageReplays, PageCommunity, PageSettings }) p.Visibility = p == page ? Visibility.Visible : Visibility.Collapsed;
            if (page != PageSettings) SaveQuiet();
        }

        void Tab_Checked(object sender, RoutedEventArgs e)
        {
            if (PageHome == null) return;
            ShowPage(sender == TabReplays ? PageReplays : sender == TabCommunity ? PageCommunity : sender == TabSettings ? (UIElement)PageSettings : PageHome);
        }

        void Section_Checked(object sender, RoutedEventArgs e)
        {
            if (BoxPlayer == null) return;
            var map = new Dictionary<object, UIElement> { { SecPlayer, BoxPlayer }, { SecOnline, BoxOnline }, { SecVideo, BoxVideo }, { SecPads, BoxPads }, { SecSaves, BoxSaves }, { SecDlc, BoxDlc }, { SecFiles, BoxFiles } };
            foreach (var kv in map) kv.Value.Visibility = kv.Key == sender ? Visibility.Visible : Visibility.Collapsed;
        }

        void OpenSettings(RadioButton section)
        {
            section.IsChecked = true;
            TabSettings.IsChecked = true;
        }

        /// <summary>--page replays | community | settings[:player|online|video|controllers|saves|dlc|files] (for screenshots)</summary>
        void OpenFromArgs()
        {
            var args = Environment.GetCommandLineArgs();
            int i = Array.IndexOf(args, "--page");
            if (i < 0 || i + 1 >= args.Length) return;
            var parts = args[i + 1].Split(':');
            if (parts[0] == "replays") TabReplays.IsChecked = true;
            else if (parts[0] == "community") TabCommunity.IsChecked = true;
            else if (parts[0] == "settings")
            {
                var secs = new Dictionary<string, RadioButton> { { "player", SecPlayer }, { "online", SecOnline }, { "video", SecVideo }, { "controllers", SecPads }, { "saves", SecSaves }, { "dlc", SecDlc }, { "files", SecFiles } };
                OpenSettings(parts.Length > 1 && secs.ContainsKey(parts[1]) ? secs[parts[1]] : SecPlayer);
            }
        }

        void Home_Click(object sender, RoutedEventArgs e) { TabHome.IsChecked = true; }
        void Gear_Click(object sender, RoutedEventArgs e) { OpenSettings(SecPlayer); }
        void Configure_Click(object sender, RoutedEventArgs e) { OpenSettings(SecOnline); }
        void Profile_Click(object sender, RoutedEventArgs e) { OpenSettings(SecPlayer); }
        void Controller_Click(object sender, RoutedEventArgs e) { OpenSettings(SecPads); FindPads(); }
        void Files_Click(object sender, RoutedEventArgs e) { OpenSettings(SecFiles); }
        void Community_Click(object sender, RoutedEventArgs e) { TabCommunity.IsChecked = true; }
        void Site_Click(object sender, RoutedEventArgs e) { Core.Open(Core.Site); }
        void Project_Click(object sender, RoutedEventArgs e) { Core.Open(Core.Site + "project"); }
        void Started_Click(object sender, RoutedEventArgs e) { Core.Open(Core.Site + "getting-started"); }
        void Recomp_Click(object sender, RoutedEventArgs e) { Core.Open("https://github.com/Denkishi/ssbu-recomp"); }
        void FrameData_Click(object sender, RoutedEventArgs e) { Core.Open("https://ultimateframedata.com/"); }

        void CopyCode_Click(object sender, RoutedEventArgs e)
        {
            try { Clipboard.SetText(Core.Code.Trim() == "" ? "public" : Core.Code.Trim()); Status("Friend code copied", "good"); } catch { }
        }

        void Minimize_Click(object sender, RoutedEventArgs e) { WindowState = WindowState.Minimized; }
        void Maximize_Click(object sender, RoutedEventArgs e) { WindowState = WindowState == WindowState.Maximized ? WindowState.Normal : WindowState.Maximized; }
        void Close_Click(object sender, RoutedEventArgs e) { Close(); }

        // ---------------------------------------------------------------- dialog
        /// <summary>a modal card over the window; each button: (label, action or null, primary?)</summary>
        void Show(string title, string text, IEnumerable<string> list, params (string label, Action act, bool primary)[] buttons)
        {
            DialogTitle.Text = title.ToUpperInvariant();
            DialogText.Text = text ?? "";
            DialogText.Visibility = string.IsNullOrEmpty(text) ? Visibility.Collapsed : Visibility.Visible;
            DialogList.ItemsSource = list?.Select(l => new TextBlock { Text = l, FontFamily = new FontFamily("Consolas"), FontSize = 13, Foreground = Res("Muted"), TextWrapping = TextWrapping.Wrap, Margin = new Thickness(0, 2, 0, 2) }).ToList();
            DialogButtons.Children.Clear();
            foreach (var b in buttons)
            {
                var btn = new Button { Content = b.label, Height = 44, Margin = new Thickness(10, 0, 0, 0), MinWidth = 110, FontSize = 15, Padding = new Thickness(22, 0, 22, 0) };
                if (b.primary)
                {
                    btn.Style = (Style)Application.Current.Resources["Primary"];
                    btn.Content = new TextBlock { Text = b.label, FontSize = 15, FontWeight = FontWeights.SemiBold, Foreground = new SolidColorBrush(Color.FromRgb(6, 18, 29)), Margin = new Thickness(22, 0, 22, 0) };
                }
                else btn.Style = (Style)Application.Current.Resources["Outline"];
                var act = b.act;
                btn.Click += (s, e) => { Dialog.Visibility = Visibility.Collapsed; act?.Invoke(); };
                DialogButtons.Children.Add(btn);
            }
            Dialog.Visibility = Visibility.Visible;
        }

        // ---------------------------------------------------------------- play
        void Play_Click(object sender, RoutedEventArgs e)
        {
            if (!SaveQuiet()) return;
            if (Core.GameRunning()) { Show("Already running", "The game is already open.", null, ("OK", null, true)); return; }
            var bad = Core.CheckOnline();
            if (bad.Count > 0) { Show("Online settings", null, bad, ("Open settings", () => OpenSettings(SecOnline), true), ("Cancel", null, false)); return; }
            if (checks == null) { Status("Still checking the game files...", "busy"); return; }
            var badFiles = checks.Where(c => !c.Ok).ToList();
            if (badFiles.Count > 0)
            {
                bool onlyCodecs = badFiles.Count == missingCodecs.Count && missingCodecs.Count > 0;
                if (onlyCodecs)
                    Show("Missing video codecs", "The opening movie needs these Microsoft Store packages; without them the game starts on a black screen.",
                         missingCodecs.Select(m => m.Split('|')[1]),
                         ("Install", InstallCodecs, true), ("Cancel", null, false));
                else Show("The game is not ready", null, badFiles.Select(c => c.Text), ("Game files", () => OpenSettings(SecFiles), true), ("Cancel", null, false));
                return;
            }
            Action go = () =>
            {
                if (Core.CanPrepare() && Core.NeedsPrepare()) { StartPrep(true); return; }      // the shaders first, here, with progress: the game then starts without the long wait
                Start();
            };
            Core.Ticket = null;
            if (!(Core.Online && Core.HasOnline)) { go(); return; }
            // online: a fresh lobby ticket for this start (the lobby refuses a game without one)
            PlayButton.IsEnabled = false;
            Status("Checking your account...", "busy");
            Task.Run(() => Account.LobbyTicket()).ContinueWith(t =>
            {
                PlayButton.IsEnabled = true;
                if (t.IsFaulted) { SetState(); Show("Online", "Could not get your online pass: " + t.Exception.GetBaseException().Message, null, ("Play offline", () => { Core.Online = false; OnlineBox.IsChecked = false; SaveQuiet(); RefreshOnline(); go(); }, false), ("OK", null, true)); return; }
                Core.Ticket = t.Result;
                SetState();
                go();
            }, TaskScheduler.FromCurrentSynchronizationContext());
        }

        // ---------------------------------------------------------------- account (Account.cs)
        void ResumeAccount()
        {
            Status("Signing in...", "busy");
            Task.Run(() => { bool ok = Account.Resume(out var err); return Tuple.Create(ok, err); }).ContinueWith(t =>
            {
                ApplyAccount();
                SetState();
                if (!t.Result.Item1) ShowLogin(t.Result.Item2 != null ? "Cannot reach the Arena server: " + t.Result.Item2 : null);
            }, TaskScheduler.FromCurrentSynchronizationContext());
        }

        /// <summary>the account into the window: the player card, Settings > Player, the online state</summary>
        void ApplyAccount()
        {
            bool on = Account.SignedIn;
            AccountBox.Visibility = on ? Visibility.Visible : Visibility.Collapsed;
            OfflineBox.Visibility = on ? Visibility.Collapsed : Visibility.Visible;
            if (on)
            {
                AccountName.Text = Account.Me.Display.ToUpperInvariant();
                AccountEmail.Text = Account.Me.Email;
                Core.Nickname = Account.Me.Username;
            }
            RefreshPlayer();
            RefreshOnline();
        }

        void ShowLogin(string error = null)
        {
            LoginError.Text = error ?? "";
            LoginError.Visibility = string.IsNullOrEmpty(error) ? Visibility.Collapsed : Visibility.Visible;
            LoginOverlay.Visibility = Visibility.Visible;
            LoginButton.Focus();
        }

        System.Threading.CancellationTokenSource browserLogin;

        /// <summary>sign-in in the browser (Account.SignInWithBrowser): ssbuarena.com/launcher, with its CAPTCHA; a second press
        /// starts it again (a new page, the old wait is dropped)</summary>
        void Login_Click(object sender, RoutedEventArgs e)
        {
            browserLogin?.Cancel();
            var cts = browserLogin = new System.Threading.CancellationTokenSource();
            LoginError.Visibility = Visibility.Collapsed;
            LoginWaiting.Visibility = Visibility.Visible;
            LoginButtonText.Text = "OPEN AGAIN";
            Task.Run(() => Account.SignInWithBrowser(cts.Token)).ContinueWith(t =>
            {
                if (cts.IsCancellationRequested) return;          // a newer attempt took over
                browserLogin = null;
                LoginWaiting.Visibility = Visibility.Collapsed;
                LoginButtonText.Text = "SIGN IN";
                if (t.IsFaulted) { ShowLogin(t.Exception.GetBaseException().Message); return; }
                LoginOverlay.Visibility = Visibility.Collapsed;
                ApplyAccount();
                SetState();
                Status("Signed in as " + Account.Me.Display, "good");
                Activate();
            }, TaskScheduler.FromCurrentSynchronizationContext());
        }
        void CreateAccount_Click(object sender, RoutedEventArgs e) { Core.Open(Account.SignUpPage); }
        void ManageAccount_Click(object sender, RoutedEventArgs e) { Core.Open(Account.AccountPage); }
        void ShowLogin_Click(object sender, RoutedEventArgs e) { ShowLogin(); }

        void PlayOffline_Click(object sender, RoutedEventArgs e)
        {
            browserLogin?.Cancel(); browserLogin = null;
            LoginWaiting.Visibility = Visibility.Collapsed; LoginButtonText.Text = "SIGN IN";
            LoginOverlay.Visibility = Visibility.Collapsed;
            Status("Offline: local play only", "warn");
            RefreshOnline();
        }

        void SignOut_Click(object sender, RoutedEventArgs e)
        {
            Account.SignOut();
            ApplyAccount();
            ShowLogin();
        }

        void InstallCodecs()
        {
            Status("Installing video codecs...", "busy");
            var ids = missingCodecs.Select(m => m.Split('|')[0]).ToList();
            Task.Run(() => { foreach (var id in ids) Core.InstallCodec(id); }).ContinueWith(t => RunChecks(), TaskScheduler.FromCurrentSynchronizationContext());
        }

        // ---------------------------------------------------------------- updates (Updater.cs)
        Process updating;
        Release release;
        List<string> updSteps = new List<string>();
        static readonly System.Text.RegularExpressions.Regex UpdField = new System.Text.RegularExpressions.Regex("\"(\\w+)\":\\s*(?:\"([^\"]*)\"|(-?[\\d.]+)|(true|false))");

        /// <summary>at every start: the latest release (in the background); then a newer launcher, the game's update or the
        /// first install. Offline or no release: the launcher goes on as it is.</summary>
        void CheckUpdates()
        {
            Updater.CleanUp();
            try { System.IO.File.Delete(System.IO.Path.Combine(Core.Repo ?? System.IO.Path.GetDirectoryName(Updater.ExePath), Core.Repo != null ? @"build\launcher_update.log" : "launcher_update.log")); } catch { }
            Updater.Log("launcher " + Updater.Current + ", repo " + (Core.Repo ?? "(not installed)") + ", build " + Core.Build + (Updater.DevCopy ? ", git checkout" : ""));
            if (Updater.Off) { Updater.Log("SSBU_ARENA_UPDATE=off"); return; }
            Task.Run(() => { try { return Updater.Latest(); } catch (Exception ex) { Updater.Log("release check failed: " + ex.Message); return null; } }).ContinueWith(t =>
            {
                release = t.Result;
                if (release != null)
                    Updater.Log("latest release " + release.Tag + " (version " + release.Version + ", commit " + release.Commit + "); installed commit " +
                                (Updater.Installed ? Updater.InstalledCommit() ?? "unknown" : "-") + "; game exe " + (System.IO.File.Exists(Core.Exe) ? "there" : "missing"));
                if (!Updater.Installed)
                {
                    if (release == null) Show("SSBU Arena", "The first install downloads SSBU Arena from GitHub: no connection or no release found. Check the internet connection and start the launcher again.", null, ("OK", null, true));
                    else Show("Install SSBU Arena", "SSBU Arena " + release.Version + " is installed in this folder:\n" + System.IO.Path.GetDirectoryName(Updater.ExePath) +
                              "\n\nThe installer then asks for your own game files (about 25 GB of space).", null, ("Install", () => FirstInstall(), true), ("Not now", null, false));
                    return;
                }
                if (release == null || Updater.DevCopy) return;
                if (Updater.LauncherOutdated(release)) { UpdateLauncher(); return; }
                if (Updater.GameOutdated(release))
                {
                    if (!System.IO.File.Exists(Core.Exe)) return;     // the install is not finished: its installer does it
                    UpdateGame();
                }
            }, TaskScheduler.FromCurrentSynchronizationContext());
        }

        void UpdateLauncher()
        {
            Status("Updating the launcher to " + release.Version, "busy");
            Task.Run(() => Updater.ReplaceLauncher(release)).ContinueWith(t =>
            {
                if (t.Exception == null) { SaveQuiet(); Application.Current.Shutdown(); return; }
                Status("The launcher could not update itself: " + t.Exception.GetBaseException().Message, "warn");
                if (Updater.GameOutdated(release) && System.IO.File.Exists(Core.Exe)) UpdateGame();
            }, TaskScheduler.FromCurrentSynchronizationContext());
        }

        void ShowBusy(string title, string detail, string note)
        {
            TabHome.IsChecked = true;
            PlayButtons.Visibility = Visibility.Collapsed; PrepPanel.Visibility = Visibility.Visible; PrepCancel.Visibility = Visibility.Collapsed;
            PrepTitle.Text = title; PrepPct.Text = "0%"; SetPrepBar(0);
            PrepDetail.Text = detail; PrepEta.Text = ""; PrepNote.Text = note;
            StateText.Text = Spaced(title); StateDot.Fill = Res("Accent");
        }

        void HideBusy()
        {
            PrepPanel.Visibility = Visibility.Collapsed; PrepCancel.Visibility = Visibility.Visible; PlayButtons.Visibility = Visibility.Visible;
            SetState();
        }

        void UpdateGame() { UpdateGame(0); }

        void UpdateGame(int attempt)
        {
            // the launcher's own short runs of the game (FindPads: --pad-list at the start) count as running: wait for them
            if (updating == null && prep == null && game == null && Core.GameRunning() && attempt < 20)
            {
                var again = new DispatcherTimer { Interval = TimeSpan.FromSeconds(3) };
                again.Tick += (s, e) => { again.Stop(); UpdateGame(attempt + 1); };
                again.Start();
                return;
            }
            if (updating != null || prep != null || game != null || Core.GameRunning())
            {
                Updater.Log("game update not started: " + (updating != null ? "already updating" : prep != null ? "shaders being prepared" : "the game is running"));
                if (updating == null && game == null && prep == null) Status("Close the game to update SSBU Arena to " + release.Version, "warn");
                return;
            }
            Updater.Log("game update: scripts\\install.py (log: build\\update_last.log)");
            ShowBusy("UPDATING", "Downloading " + release.Tag + "...", "SSBU Arena " + release.Version + ": the game starts as soon as it is done.");
            Status("Updating SSBU Arena to " + release.Version, "busy");
            updSteps.Clear();
            try { updating = Updater.RunGameUpdate(l => Dispatcher.BeginInvoke(new Action(() => UpdateLine(l))), c => Dispatcher.BeginInvoke(new Action(() => UpdateEnded(c)))); }
            catch (Exception ex) { updating = null; HideBusy(); Show("Update", ex.Message, null, ("OK", null, true)); }
        }

        /// <summary>install.py's "##ssbu {json}" lines: the plan (step ids), each step's start, the progress inside a step</summary>
        void UpdateLine(string l)
        {
            if (!l.StartsWith("##ssbu ")) return;
            var v = new Dictionary<string, string>();
            foreach (System.Text.RegularExpressions.Match m in UpdField.Matches(l))
                v[m.Groups[1].Value] = m.Groups[2].Success ? m.Groups[2].Value : m.Groups[3].Success ? m.Groups[3].Value : m.Groups[4].Value;
            v.TryGetValue("ev", out var ev);
            if (ev == "plan") { foreach (System.Text.RegularExpressions.Match m in new System.Text.RegularExpressions.Regex("\"id\":\\s*\"([^\"]+)\"").Matches(l)) updSteps.Add(m.Groups[1].Value); return; }
            if (!v.TryGetValue("id", out var id)) return;
            int i = Math.Max(0, updSteps.IndexOf(id)), n = Math.Max(1, updSteps.Count);
            double inside = 0;
            if (ev == "progress" && double.TryParse(v.ContainsKey("done") ? v["done"] : "0", System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out var d)
                && double.TryParse(v.ContainsKey("total") ? v["total"] : "0", System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out var tot) && tot > 0)
                inside = Math.Min(1, d / tot);
            if (ev == "step" && v.TryGetValue("state", out var st) && st != "start") inside = 1;
            double f = (i + inside) / n;
            PrepPct.Text = (int)(f * 100) + "%";
            SetPrepBar(f);
            if (ev == "step" && v.TryGetValue("state", out var s2) && s2 == "start") PrepDetail.Text = UpdateStepName(id);
        }

        static string UpdateStepName(string id)
        {
            switch (id)
            {
                case "update": return "Downloading the new version";
                case "precheck": return "Checking this PC";
                case "packages": case "tools": case "media": return "Getting the tools";
                case "inputs": case "dump": case "dlc": return "Checking the game files";
                case "build": case "compile": case "nro": case "link": case "lift": return "Rebuilding the changed parts";
                case "unblock": case "shortcuts": return "Finishing";
                default: return "Updating (" + id + ")";
            }
        }

        void UpdateEnded(int code)
        {
            updating = null;
            HideBusy();
            Core.Load();
            RunChecks();
            if (code == 0) { Status("SSBU Arena updated to " + release.Version, "good"); return; }
            Show("Update failed", "SSBU Arena could not update to " + release.Version + " (exit code " + code + "). The game you had is still there. Last lines of build\\update_last.log:",
                 Updater.UpdateLogTail(8), ("Try again", () => UpdateGame(), false), ("OK", null, true));
        }

        void FirstInstall()
        {
            ShowBusy("INSTALLING", "Downloading...", "Then the installer asks for your own game files.");
            Task.Run(() => Updater.FirstInstall(release, s => Dispatcher.BeginInvoke(new Action(() => PrepDetail.Text = s)))).ContinueWith(t =>
            {
                if (t.Exception != null) { HideBusy(); Show("Install", t.Exception.GetBaseException().Message, null, ("OK", null, true)); return; }
                PrepDetail.Text = "The installer is open: follow it, then this launcher starts again.";
                SetPrepBar(1); PrepPct.Text = "";
                var p = t.Result;
                p.EnableRaisingEvents = true;
                p.Exited += (s, e) =>
                {
                    Updater.WaitInstallerWindow(System.IO.Path.GetDirectoryName(Updater.ExePath));
                    Dispatcher.BeginInvoke(new Action(() =>
                    {
                        Process.Start(new ProcessStartInfo(Updater.ExePath) { UseShellExecute = false });
                        Application.Current.Shutdown();
                    }));
                };
            }, TaskScheduler.FromCurrentSynchronizationContext());
        }

        // ---------------------------------------------------------------- shader preparation
        Process prep;
        bool prepThenPlay, prepCancelled;
        static readonly System.Text.RegularExpressions.Regex PrepField = new System.Text.RegularExpressions.Regex("\"(\\w+)\":(?:\"([^\"]*)\"|(-?\\d+))");

        /// <summary>the game prepares the shaders hidden (Core.StartPrepare); the hero shows the progress; thenPlay: the
        /// match starts when it is done</summary>
        void StartPrep(bool thenPlay)
        {
            if (prep != null || game != null) return;
            if (Core.GameRunning()) { Show("Already running", "Close the game first.", null, ("OK", null, true)); return; }
            prepThenPlay = thenPlay; prepCancelled = false;
            TabHome.IsChecked = true;
            PlayButtons.Visibility = Visibility.Collapsed; PrepPanel.Visibility = Visibility.Visible;
            PrepTitle.Text = "PREPARING SHADERS"; PrepPct.Text = "0%"; SetPrepBar(0);
            PrepDetail.Text = "Starting the game in the background..."; PrepEta.Text = "";
            PrepNote.Text = thenPlay ? "Once per graphics card and driver: the game starts right after." : "Once per graphics card and driver.";
            StateText.Text = Spaced("PREPARING SHADERS"); StateDot.Fill = Res("Accent");
            Status("Preparing the shaders for this graphics card", "busy");
            try { prep = Core.StartPrepare(l => Dispatcher.BeginInvoke(new Action(() => PrepLine(l))), c => Dispatcher.BeginInvoke(new Action(() => PrepEnded(c)))); }
            catch (Exception ex) { prep = null; PrepPanel.Visibility = Visibility.Collapsed; PlayButtons.Visibility = Visibility.Visible; SetState(); Show("Could not prepare the shaders", ex.Message, null, ("OK", null, true)); }
        }

        void SetPrepBar(double f)
        {
            f = Math.Max(0, Math.Min(1, f));
            PrepDone.Width = new GridLength(f, GridUnitType.Star);
            PrepLeft.Width = new GridLength(1 - f, GridUnitType.Star);
        }

        void PrepLine(string l)
        {
            if (!l.StartsWith("##prep ")) return;
            var v = new Dictionary<string, string>();
            foreach (System.Text.RegularExpressions.Match m in PrepField.Matches(l)) v[m.Groups[1].Value] = m.Groups[2].Success && m.Groups[2].Value != "" ? m.Groups[2].Value : m.Groups[3].Value;
            if (!v.TryGetValue("state", out var st) || st != "running") return;
            int pct = v.TryGetValue("pct", out var p) && int.TryParse(p, out var pi) ? pi : 0;
            int eta = v.TryGetValue("eta", out var e) && int.TryParse(e, out var ei) ? ei : -1;
            PrepPct.Text = pct + "%";
            SetPrepBar(pct / 100.0);
            if (v.TryGetValue("phase", out var ph) && ph == "data") PrepDetail.Text = "Reading the game data";
            else PrepDetail.Text = string.Format("{0:N0} of about {1:N0} shaders", long.Parse(v.ContainsKey("done") ? v["done"] : "0"), long.Parse(v.ContainsKey("total") ? v["total"] : "0"));
            PrepEta.Text = eta >= 0 ? string.Format("about {0}:{1:00} left", eta / 60, eta % 60) : "";
        }

        void PrepEnded(int code)
        {
            prep = null;
            PrepPanel.Visibility = Visibility.Collapsed; PlayButtons.Visibility = Visibility.Visible;
            RunChecks();
            if (prepCancelled) { Status("Shader preparation stopped: it goes on from where it was next time", "warn"); return; }
            if (code == 0) { Core.ShaderStamp = Core.ShaderKey(); SaveQuiet(); Status("Shaders prepared", "good"); if (prepThenPlay) Start(); return; }
            if (code == 3) { if (prepThenPlay) Start(); else Show("Shaders", "This graphics card prepares its shaders while you play (no stage libraries): nothing to do here.", null, ("OK", null, true)); return; }
            Show("Shader preparation failed", "Exit code " + code + ". Last lines of build\\prepare.log:", Core.PrepareLogTail(8),
                 ("Play anyway", () => Start(), false), ("OK", null, true));
        }

        void PrepCancel_Click(object sender, RoutedEventArgs e)
        {
            if (prep == null) return;
            prepCancelled = true;
            try { prep.Kill(); } catch { }
        }

        void PrepareNow_Click(object sender, RoutedEventArgs e)
        {
            if (!SaveQuiet()) return;
            if (!Core.CanPrepare()) { Show("Shaders", "This build of the game cannot prepare its shaders outside the game yet: it prepares them itself at its first start.", null, ("OK", null, true)); return; }
            StartPrep(false);
        }

        void Start()
        {
            bool first = Core.FirstRun();
            try { game = Core.Launch(); }
            catch (Exception ex) { Show("Could not start the game", ex.Message, null, ("OK", null, true)); return; }
            game.Exited += (s, e) => Dispatcher.Invoke(GameExited);
            SetState();
            if (first) StatusText.Text = "First start: the game prepares the shaders for this graphics card (a few minutes)";
            ToTray();
        }

        // ---------------------------------------------------------------- the notification area while the game runs
        System.Windows.Forms.NotifyIcon tray;

        /// <summary>while the game runs the launcher leaves the screen and the taskbar for the notification area (the hidden
        /// icons), as game launchers do; the icon's menu or a double click brings it back</summary>
        void ToTray()
        {
            if (tray == null)
            {
                tray = new System.Windows.Forms.NotifyIcon { Text = "SSBU Arena", Icon = System.Drawing.Icon.ExtractAssociatedIcon(Updater.ExePath) };
                var menu = new System.Windows.Forms.ContextMenuStrip();
                menu.Items.Add("Open SSBU Arena", null, (s, e) => Dispatcher.Invoke(FromTray));
                menu.Items.Add("Quit the launcher", null, (s, e) => Dispatcher.Invoke(() => { HideTray(); Application.Current.Shutdown(); }));
                tray.ContextMenuStrip = menu;
                tray.DoubleClick += (s, e) => Dispatcher.Invoke(FromTray);
                Closed += (s, e) => HideTray();
            }
            tray.Visible = true;
            Hide();
        }

        void FromTray()
        {
            base.Show();
            if (WindowState == WindowState.Minimized) WindowState = WindowState.Normal;
            Activate();
        }

        void HideTray() { if (tray != null) { tray.Visible = false; tray.Dispose(); tray = null; } }

        void GameExited()
        {
            game = null;
            HideTray();
            FromTray();
            SetState();
        }
    }
}
