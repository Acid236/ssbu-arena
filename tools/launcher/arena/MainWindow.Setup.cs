// SPDX-License-Identifier: GPL-3.0-or-later
// SSBU Arena launcher: the setup screen (the work is in Installer.cs). Stage 1 downloads the release's sources (first
// install only) and prepares the tools; stage 2 shows the game files the scan found, each can be changed, and checks
// the PC; stage 3 runs install.py with its steps, one bar, the time left and the log. install.py is resumable: after an
// error or Stop the button says Resume. At the end the launcher starts again on the installed game.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Threading;

namespace Arena
{
    public partial class MainWindow
    {
        sealed class SetupStep
        {
            public string Id, Title, State = "wait";
            public double Est = 1, Secs, Done, Total;
            public DateTime T0;
        }

        string setupPy;
        Found found;
        SetupChoice choice;
        Process setupProc;
        bool setupRunning, setupOk, setupStopped, setupDownload;
        List<SetupStep> setupSteps = new List<SetupStep>();
        DateTime setupStart;
        DispatcherTimer setupTimer, precheckLater;
        readonly Queue<string> setupLog = new Queue<string>();

        /// <summary>the setup screen; download: the release's sources first (the launcher was downloaded alone)</summary>
        void StartSetup(bool download)
        {
            setupDownload = download;
            SetupOverlay.Visibility = Visibility.Visible;
            SetupStageOn(1);
            SetupIntro.Text = "SSBU Arena runs your own copy of Super Smash Bros. Ultimate (13.0.4 or 13.0.5) natively on this PC. " +
                              "Nothing of the game is downloaded: the setup builds it from your files, here. About 25 GB of space; it takes a while once.";
            SetupBusy.Visibility = Visibility.Visible; SetupFiles.Visibility = Visibility.Collapsed; SetupRun.Visibility = Visibility.Collapsed;
            SetupFooter.Visibility = Visibility.Collapsed; SetupBusyButtons.Visibility = Visibility.Collapsed;
            SetupBusyTitle.Text = download ? "DOWNLOADING SSBU ARENA" : "PREPARING THE TOOLS";
            SetupBusyDetail.Foreground = Res("Muted");
            SetupBusyDetail.Text = download ? "SSBU Arena " + release?.Version + " from GitHub..." : "A private Python and its packages, inside this folder only (nothing is installed on Windows).";
            SetupBusyLog.Text = "";
            SetBar(SetupBusyDone, SetupBusyLeft, 0.05);
            Action<string> say = s => Dispatcher.BeginInvoke(new Action(() => SetupBusyLog.Text = s));
            Task.Run(() =>
            {
                if (download)
                {
                    Updater.FirstInstall(release, s => Dispatcher.BeginInvoke(new Action(() => SetupBusyDetail.Text = s)));
                    Dispatcher.Invoke(() =>
                    {
                        SetupBusyTitle.Text = "PREPARING THE TOOLS"; SetBar(SetupBusyDone, SetupBusyLeft, 0.35);
                        SetupBusyDetail.Text = "A private Python and its packages, inside this folder only (nothing is installed on Windows).";
                    });
                }
                string py = Installer.PrepareTools(say);
                Dispatcher.Invoke(() => { SetupBusyTitle.Text = "LOOKING FOR YOUR GAME FILES"; SetBar(SetupBusyDone, SetupBusyLeft, 0.8); SetupBusyDetail.Text = "Emulator folders, Downloads, Desktop and the other usual places: only names and headers are read."; });
                return Tuple.Create(py, Installer.Scan(py));
            }).ContinueWith(t =>
            {
                if (t.IsFaulted)
                {
                    SetupBusyTitle.Text = "THE SETUP STOPPED";
                    SetupBusyDetail.Foreground = Res("Bad");
                    SetupBusyDetail.Text = t.Exception.GetBaseException().Message;
                    SetupBusyButtons.Visibility = Visibility.Visible;
                    return;
                }
                setupPy = t.Result.Item1;
                found = t.Result.Item2;
                ShowSetupFiles(true);
            }, TaskScheduler.FromCurrentSynchronizationContext());
        }

        void SetupRetry_Click(object sender, RoutedEventArgs e)
        {
            StartSetup(setupDownload && !File.Exists(Path.Combine(Installer.Root, @"scripts\install.py")));
        }

        void SetupStageOn(int n)
        {
            var all = new[] { SetupStage1, SetupStage2, SetupStage3 };
            for (int i = 0; i < 3; i++) all[i].Foreground = i + 1 == n ? Res("Accent") : i + 1 < n ? Res("Text") : Res("Dim");
        }

        static void SetBar(ColumnDefinition done, ColumnDefinition left, double f)
        {
            f = Math.Max(0, Math.Min(1, f));
            done.Width = new GridLength(f, GridUnitType.Star);
            left.Width = new GridLength(1 - f, GridUnitType.Star);
        }

        // ---------------------------------------------------------------- stage 2: the game files
        void ShowSetupFiles(bool fill)
        {
            SetupStageOn(2);
            SetupIntro.Text = "These are the files found on this PC: check them, change any with File or Folder. " +
                              "A dump already decrypted on your Switch (a folder with exefs and romfs, e.g. from nxdumptool) needs no prod.keys and no update.";
            SetupBusy.Visibility = Visibility.Collapsed; SetupRun.Visibility = Visibility.Collapsed; SetupFiles.Visibility = Visibility.Visible;
            SetupFooter.Visibility = Visibility.Visible; SetupLogButton.Visibility = Visibility.Collapsed;
            SetupBack.Visibility = Visibility.Collapsed; SetupStop.Visibility = Visibility.Collapsed; SetupTools.Visibility = Visibility.Collapsed;
            SetupGoText.Text = "INSTALL";
            if (fill && found != null)
            {
                bool was = loading;
                loading = true;
                SetupGame.Text = found.Dump ?? found.Base ?? "";
                SetupUpdate.Text = found.Update ?? "";
                SetupKeys.Text = found.Keys ?? "";
                SetupFirmware.Text = found.Firmware ?? "";
                SetupLocation.Text = Core.Repo != null ? Core.Build : Installer.DefaultLocation;
                SetupDlc.IsChecked = found.Dlc.Count > 0;
                loading = was;
            }
            CheckSetupFields();
            RunPrecheck();
        }

        void SetupField_Changed(object sender, RoutedEventArgs e) { if (!loading) CheckSetupFields(); }

        void SetupLocation_Changed(object sender, RoutedEventArgs e)
        {
            if (loading) return;
            CheckSetupFields();
            // the disk check again, once the typing stops
            precheckLater?.Stop();
            precheckLater = new DispatcherTimer { Interval = TimeSpan.FromSeconds(1) };
            precheckLater.Tick += (s, a) => { precheckLater.Stop(); RunPrecheck(); };
            precheckLater.Start();
        }

        static string Clean(TextBox b) => b.Text.Trim().Trim('"');

        static void FieldState(ContentControl mark, TextBlock text, string kind, string msg)
        {
            mark.Content = Mark(kind, 20);
            text.Text = msg;
            text.Foreground = kind == "bad" ? Res("Bad") : Res("Muted");
        }

        /// <summary>each field's state line; Install only when the game can be built from them</summary>
        bool CheckSetupFields()
        {
            string game = Clean(SetupGame), upd = Clean(SetupUpdate), keys = Clean(SetupKeys), fw = Clean(SetupFirmware);
            bool dump = Installer.IsDump(game), ok = true;
            if (game == "") { FieldState(SetupGameMark, SetupGameText, "bad", "Choose your game: its .xci / .nsp / .nsz file, or a dump folder (exefs and romfs)."); ok = false; }
            else if (dump) FieldState(SetupGameMark, SetupGameText, "ok", "A decrypted dump: no prod.keys and no update needed.");
            else if (File.Exists(game)) FieldState(SetupGameMark, SetupGameText, "ok", "Your game package" + (string.Equals(game, found?.Base, StringComparison.OrdinalIgnoreCase) ? " (found on this PC)." : "."));
            else if (Directory.Exists(game)) FieldState(SetupGameMark, SetupGameText, "warn", "A folder without exefs and romfs: the setup looks inside it for the game package.");
            else { FieldState(SetupGameMark, SetupGameText, "bad", "Not found."); ok = false; }

            SetupPackageFields.Visibility = dump ? Visibility.Collapsed : Visibility.Visible;
            if (!dump)
            {
                if (upd == "") { FieldState(SetupUpdateMark, SetupUpdateText, "bad", "Needed: your game's update 13.0.4 or 13.0.5 (.nsp / .nsz)."); ok = false; }
                else if (File.Exists(upd) || Directory.Exists(upd))
                    FieldState(SetupUpdateMark, SetupUpdateText, "ok", string.Equals(upd, found?.Update, StringComparison.OrdinalIgnoreCase) && found?.Build != null ? "Update " + found.Build + " (found on this PC)." : "Your update.");
                else { FieldState(SetupUpdateMark, SetupUpdateText, "bad", "Not found."); ok = false; }

                if (keys == "") { FieldState(SetupKeysMark, SetupKeysText, "bad", "Needed to decrypt your game package. Or choose a decrypted dump folder above instead."); ok = false; }
                else if (File.Exists(keys)) FieldState(SetupKeysMark, SetupKeysText, "ok", "Used where it is: never copied, never sent anywhere.");
                else { FieldState(SetupKeysMark, SetupKeysText, "bad", "Not found."); ok = false; }

                int n = found?.Dlc.Count ?? 0;
                SetupDlc.IsEnabled = n > 0;
                SetupDlcTitle.Text = n == 0 ? "No DLC found" : "Add your DLC (" + n + " found)";
                SetupDlcText.Text = n == 0 ? "DLC can be added later in Settings > DLC." : "The DLC packages found next to your game: their fighters, stages and music.";
            }

            if (fw == "") FieldState(SetupFirmwareMark, SetupFirmwareText, "ok", "Not needed: open-source fonts are used (no Chinese, Japanese or Korean text).");
            else if (Directory.Exists(fw)) FieldState(SetupFirmwareMark, SetupFirmwareText, "ok", "Your console's own system fonts are taken from it.");
            else FieldState(SetupFirmwareMark, SetupFirmwareText, "warn", "Not found: the open-source fonts are used instead.");

            if (Clean(SetupLocation) == "") ok = false;
            SetupGo.IsEnabled = ok;
            return ok;
        }

        SetupChoice ReadChoice()
        {
            string game = Clean(SetupGame), fw = Clean(SetupFirmware);
            bool dump = Installer.IsDump(game);
            var c = new SetupChoice
            {
                Game = game,
                Update = dump ? null : Clean(SetupUpdate),
                Keys = dump ? null : Clean(SetupKeys),
                Firmware = Directory.Exists(fw) ? fw : null,
                Location = Clean(SetupLocation) == "" ? Installer.DefaultLocation : Clean(SetupLocation),
                Jobs = choice?.Jobs ?? 0,
            };
            if (!dump && SetupDlc.IsChecked == true && found != null) c.Dlc = found.Dlc.ToList();
            return c;
        }

        void RunPrecheck()
        {
            if (setupPy == null) return;
            var c = ReadChoice();
            SetupPc.ItemsSource = new[] { CheckRow(true, "Checking this PC...", "busy") };
            Task.Run(() => Installer.Precheck(setupPy, c)).ContinueWith(t =>
            {
                if (t.IsFaulted) { SetupPc.ItemsSource = new[] { CheckRow(false, "The PC check did not run: " + t.Exception.GetBaseException().Message, "warn") }; return; }
                var rows = new List<UIElement>();
                foreach (var p in t.Result)
                {
                    var sp = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 6, 0, 6) };
                    sp.Children.Add(Mark(p.Level == "ok" ? "ok" : p.Level == "warn" ? "warn" : "bad", 20));
                    var txt = new StackPanel { Margin = new Thickness(12, 0, 0, 0) };
                    txt.Children.Add(new TextBlock { Text = p.What, FontSize = 14, FontWeight = FontWeights.SemiBold });
                    txt.Children.Add(new TextBlock { Text = p.Msg, FontSize = 13, Foreground = Res("Muted"), TextWrapping = TextWrapping.Wrap, MaxWidth = 280 });
                    sp.Children.Add(txt);
                    rows.Add(sp);
                    // the memory check suggests the compiler jobs this PC can hold ("--jobs 10")
                    var m = System.Text.RegularExpressions.Regex.Match(p.Msg ?? "", @"--jobs (\d+)");
                    if (p.What == "Memory" && m.Success) { if (choice == null) choice = new SetupChoice(); choice.Jobs = int.Parse(m.Groups[1].Value); }
                }
                SetupPc.ItemsSource = rows;
            }, TaskScheduler.FromCurrentSynchronizationContext());
        }

        static string PickFile(string title, string filter)
        {
            var d = new Microsoft.Win32.OpenFileDialog { Title = title, Filter = filter };
            return d.ShowDialog() == true ? d.FileName : null;
        }

        void SetupGameFile_Click(object sender, RoutedEventArgs e) { var f = PickFile("Your Super Smash Bros. Ultimate (base game)", "Game (*.xci;*.nsp;*.nsz;*.xcz)|*.xci;*.nsp;*.nsz;*.xcz|All files|*.*"); if (f != null) SetupGame.Text = f; }
        void SetupGameFolder_Click(object sender, RoutedEventArgs e) { var f = PickFolder("A dump of your game decrypted on the console (exefs and romfs inside), or a folder with your game package"); if (f != null) SetupGame.Text = f; }
        void SetupUpdateFile_Click(object sender, RoutedEventArgs e) { var f = PickFile("Your game's update 13.0.4 or 13.0.5", "Update (*.nsp;*.nsz)|*.nsp;*.nsz|All files|*.*"); if (f != null) SetupUpdate.Text = f; }
        void SetupKeysFile_Click(object sender, RoutedEventArgs e) { var f = PickFile("Your prod.keys (dumped from your Switch)", "Keys (*.keys)|*.keys|All files|*.*"); if (f != null) SetupKeys.Text = f; }
        void SetupFirmware_Click(object sender, RoutedEventArgs e) { var f = PickFolder("Your firmware dump (a folder of .nca files), or the extracted system fonts"); if (f != null) SetupFirmware.Text = f; }
        void SetupLocation_Click(object sender, RoutedEventArgs e) { var f = PickFolder("Where the game is unpacked and built (about 25 GB)"); if (f != null) SetupLocation.Text = Path.Combine(f, "SSBU Arena"); }

        void SetupRescan_Click(object sender, RoutedEventArgs e)
        {
            if (setupPy == null) return;
            SetupPc.ItemsSource = new[] { CheckRow(true, "Looking for your game files...", "busy") };
            Task.Run(() => Installer.Scan(setupPy)).ContinueWith(t =>
            {
                if (!t.IsFaulted) found = t.Result;
                ShowSetupFiles(!t.IsFaulted);
            }, TaskScheduler.FromCurrentSynchronizationContext());
        }

        // ---------------------------------------------------------------- stage 3: install.py
        void SetupGo_Click(object sender, RoutedEventArgs e)
        {
            if (setupRunning) return;
            if (setupOk) { RestartLauncher(); return; }
            if (SetupFiles.Visibility == Visibility.Visible)
            {
                if (!CheckSetupFields()) return;
                int jobs = choice?.Jobs ?? 0;
                choice = ReadChoice();
                choice.Jobs = jobs;
            }
            RunSetup();
        }

        void RunSetup()
        {
            SetupStageOn(3);
            SetupIntro.Text = "The setup unpacks your game, takes the prebuilt SSBU Arena runtime and builds the rest on this PC. " +
                              "You can stop it: it goes on from where it was.";
            SetupFiles.Visibility = Visibility.Collapsed; SetupRun.Visibility = Visibility.Visible;
            SetupLogButton.Visibility = Visibility.Visible; SetupBack.Visibility = Visibility.Collapsed; SetupTools.Visibility = Visibility.Collapsed;
            SetupStop.Visibility = Visibility.Visible; SetupGo.IsEnabled = false; SetupGoText.Text = "INSTALLING";
            SetupError.Visibility = Visibility.Collapsed;
            SetupRunTitle.Text = "INSTALLING"; SetupPct.Text = "0%"; SetupEta.Text = ""; SetupRunDetail.Text = "Starting...";
            SetBar(SetupRunDone, SetupRunLeft, 0);
            setupSteps.Clear(); SetupSteps.ItemsSource = null; setupLog.Clear(); SetupLog.Text = "";
            setupOk = setupStopped = false;
            setupRunning = true;
            setupStart = DateTime.Now;
            Updater.Log("setup: install.py " + Installer.Arguments(choice).Replace(choice.Keys ?? "\u0001", "<prod.keys>"));
            try
            {
                setupProc = Installer.Install(setupPy, choice, l => Dispatcher.BeginInvoke(new Action(() => SetupLine(l))),
                                              c => Dispatcher.BeginInvoke(new Action(() => SetupEnded(c))));
            }
            catch (Exception ex) { setupRunning = false; SetupEnded(-1, ex.Message); return; }
            setupTimer?.Stop();
            setupTimer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(1) };
            setupTimer.Tick += (s, a) => SetupProgress();
            setupTimer.Start();
        }

        Dictionary<string, object> setupDone;

        /// <summary>one line of install.py: "##ssbu {json}" events, any other line into the log box</summary>
        void SetupLine(string l)
        {
            if (!l.StartsWith("##ssbu "))
            {
                setupLog.Enqueue(l);
                while (setupLog.Count > 400) setupLog.Dequeue();
                SetupLog.Text = string.Join("\n", setupLog);
                SetupLog.ScrollToEnd();
                return;
            }
            Dictionary<string, object> ev;
            try { ev = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(l.Substring(7)); } catch { return; }
            string kind = ev.TryGetValue("ev", out var k) ? k as string : null;
            string id = ev.TryGetValue("id", out var i) ? i as string : null;
            var step = setupSteps.FirstOrDefault(s => s.Id == id);
            switch (kind)
            {
                case "plan":
                    setupSteps = ((System.Collections.ArrayList)ev["steps"]).Cast<Dictionary<string, object>>().Select(s => new SetupStep
                    {
                        Id = s["id"] as string, Title = s.TryGetValue("title", out var t) ? t as string : s["id"] as string,
                        Est = s.TryGetValue("est_s", out var est) ? Convert.ToDouble(est) : 1,
                    }).ToList();
                    break;
                case "step":
                    if (step == null) { step = new SetupStep { Id = id, Title = id }; setupSteps.Add(step); }
                    string st = ev.TryGetValue("state", out var sv) ? sv as string : "";
                    if (st == "start") { step.State = "run"; step.T0 = DateTime.Now; SetupRunDetail.Text = step.Title; }
                    else step.State = st;
                    if (ev.TryGetValue("secs", out var secs) && secs != null) step.Secs = Convert.ToDouble(secs);
                    break;
                case "progress":
                    if (step != null && ev.TryGetValue("total", out var tot) && Convert.ToDouble(tot) > 0)
                    {
                        step.Done = Convert.ToDouble(ev["done"]); step.Total = Convert.ToDouble(tot);
                        SetupRunDetail.Text = step.Title + string.Format("  ({0:N0} of {1:N0})", step.Done, step.Total);
                    }
                    break;
                case "error":
                    SetupError.Text = (ev.TryGetValue("msg", out var m) ? m as string : "The setup stopped.") +
                                      (ev.TryGetValue("hint", out var h) && !string.IsNullOrEmpty(h as string) ? "\n" + h : "");
                    SetupError.Visibility = Visibility.Visible;
                    SetupTools.Visibility = ev.TryGetValue("action", out var act) && act as string == "msvc" ? Visibility.Visible : Visibility.Collapsed;
                    break;
                case "done":
                    setupDone = ev;
                    break;
            }
            ShowSetupSteps();
            SetupProgress();
        }

        void ShowSetupSteps()
        {
            SetupSteps.ItemsSource = setupSteps.Where(s => s.Est > 0).Select(s =>
            {
                string mark = s.State == "done" || s.State == "dry" ? "ok" : s.State == "skip" ? "good" : s.State == "fail" ? "bad" : s.State == "run" ? "busy" : null;
                var sp = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 5, 0, 5) };
                sp.Children.Add(mark != null ? Mark(mark, 20) : new Border { Width = 20, Height = 20, CornerRadius = new CornerRadius(10), BorderBrush = Res("Line"), BorderThickness = new Thickness(2) });
                sp.Children.Add(new TextBlock
                {
                    Text = s.Title + (s.State == "skip" ? "  (already done)" : s.Secs >= 1 && s.State == "done" ? "  " + Dur(s.Secs) : ""),
                    FontSize = 15, Margin = new Thickness(12, 0, 0, 0), VerticalAlignment = VerticalAlignment.Center,
                    Foreground = s.State == "wait" ? Res("Dim") : s.State == "fail" ? Res("Bad") : Res("Text"),
                    FontWeight = s.State == "run" ? FontWeights.SemiBold : FontWeights.Normal,
                });
                return (UIElement)sp;
            }).ToList();
        }

        static string Dur(double s) => s < 60 ? (int)s + " s" : s < 3600 ? string.Format("{0}:{1:00} min", (int)s / 60, (int)s % 60) : string.Format("{0}:{1:00} h", (int)s / 3600, (int)s % 3600 / 60);

        /// <summary>the overall fraction, from the steps' expected seconds (a running step: its counter, else its time so
        /// far against the estimate); the time left corrected by how the finished steps went</summary>
        void SetupProgress()
        {
            double tot = 0, done = 0, rs = 0, re = 0, wait = 0, left = 0;
            foreach (var s in setupSteps)
            {
                tot += s.Est;
                double f = s.Total > 0 ? Math.Min(1, s.Done / s.Total) : s.T0 != default(DateTime) ? Math.Min(0.95, (DateTime.Now - s.T0).TotalSeconds / Math.Max(1, s.Est)) : 0;
                if (s.State == "done" || s.State == "skip" || s.State == "dry") { done += s.Est; if (s.State == "done" && s.Secs > 0) { rs += s.Secs; re += s.Est; } }
                else if (s.State == "run" || s.State == "fail") { done += s.Est * f; left += s.Est * (1 - f); }
                else wait += s.Est;
            }
            double ratio = re > 0 ? Math.Max(0.25, Math.Min(5, rs / re)) : 1;
            double frac = tot > 0 ? Math.Min(1, done / tot) : 0;
            if (setupOk) frac = 1;
            SetBar(SetupRunDone, SetupRunLeft, frac);
            SetupPct.Text = (int)(frac * 100) + "%";
            if (setupRunning)
            {
                double l = (left + wait) * ratio;
                SetupEta.Text = setupSteps.Count == 0 ? "working..." : l < 60 ? "less than a minute left" : "about " + Dur(l) + " left";
            }
        }

        void SetupEnded(int code, string why = null)
        {
            setupRunning = false;
            setupProc = null;
            setupTimer?.Stop();
            bool ok = code == 0 && (setupDone == null || !(setupDone.TryGetValue("ok", out var o) && o is bool b && !b));
            setupDone = null;
            SetupStop.Visibility = Visibility.Collapsed;
            SetupGo.IsEnabled = true;
            SetupEta.Text = "took " + Dur((DateTime.Now - setupStart).TotalSeconds);
            Updater.Log("setup: install.py ended with " + code);
            if (ok && !choice.Dry && Environment.GetEnvironmentVariable("SSBU_ARENA_SETUP_DRY") != "1")
            {
                setupOk = true;
                SetupStageOn(4);
                SetupRunTitle.Text = "READY";
                SetupRunDetail.Text = "SSBU Arena is installed.";
                SetupGoText.Text = "PLAY";
                SetupProgress();
                return;
            }
            SetupRunTitle.Text = ok ? "DRY RUN DONE" : setupStopped ? "STOPPED" : "THE SETUP STOPPED";
            SetupRunDetail.Text = ok ? "Nothing was changed (--dry-run)." : setupStopped ? "Resume goes on from where it was." : "Resume goes on from where it was, after the problem is fixed.";
            if (why != null) { SetupError.Text = why; SetupError.Visibility = Visibility.Visible; }
            else if (!ok && !setupStopped && SetupError.Visibility != Visibility.Visible)
            {
                SetupError.Text = "install.py ended with code " + code + ": the last lines of the log say why.";
                SetupError.Visibility = Visibility.Visible;
            }
            SetupGoText.Text = "RESUME";
            SetupBack.Visibility = Visibility.Visible;
        }

        void SetupStop_Click(object sender, RoutedEventArgs e)
        {
            if (setupProc == null) return;
            setupStopped = true;
            SetupRunDetail.Text = "Stopping...";
            // the whole tree: install.py runs setup.py, which runs the compilers
            try { Process.Start(new ProcessStartInfo("taskkill.exe", "/PID " + setupProc.Id + " /T /F") { CreateNoWindow = true, UseShellExecute = false }); } catch { }
        }

        void SetupBack_Click(object sender, RoutedEventArgs e) { ShowSetupFiles(false); }
        void SetupBuildTools_Click(object sender, RoutedEventArgs e) { try { Installer.InstallBuildTools(); } catch (Exception ex) { Show("Build Tools", ex.Message, null, ("OK", null, true)); } }

        void SetupOpenLog_Click(object sender, RoutedEventArgs e)
        {
            string f = choice != null ? Installer.LogPath(choice) : null;
            if (f != null && File.Exists(f)) Process.Start("notepad.exe", "\"" + f + "\"");
        }

        void RestartLauncher()
        {
            SaveQuiet();
            Process.Start(new ProcessStartInfo(Updater.ExePath) { UseShellExecute = false });
            Application.Current.Shutdown();
        }

        /// <summary>Settings > Game files: the setup again (other game files, an install location, a repair)</summary>
        void Reinstall_Click(object sender, RoutedEventArgs e)
        {
            if (game != null || prep != null || updating != null) { Show("Setup", "Close the game first.", null, ("OK", null, true)); return; }
            StartSetup(false);
        }
    }
}
