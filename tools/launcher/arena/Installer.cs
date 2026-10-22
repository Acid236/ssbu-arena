// SPDX-License-Identifier: GPL-3.0-or-later
// SSBU Arena setup, inside the launcher (MainWindow.Setup.cs shows it): the work the PowerShell installer window
// (scripts\installer_window.ps1, still used by Install SSBU.bat) does, without its window.
//   1. tools: scripts\bootstrap.ps1 -NoLaunch puts the private Python into deps\python (hidden; its lines are shown)
//   2. game files: scripts\find_inputs.py --json finds prod.keys, the game, its update, a dump, a firmware, the DLC;
//      scripts\precheck.py --json checks the PC (disk, memory, Vulkan, codecs)
//   3. scripts\install.py --no-gui --progress-json with the chosen files: "##ssbu {json}" progress lines (install.py's
//      schema: plan, step, progress, done, error), every line also in <build>\logs\installer.log
// A dump folder already decrypted on the console (exefs\ and romfs\, e.g. from nxdumptool) needs no prod.keys.
using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text;
using System.Web.Script.Serialization;

namespace Arena
{
    /// <summary>what find_inputs.py found: the best of each, plus the counts the page shows</summary>
    public sealed class Found
    {
        public string Keys, Base, Update, Build, Dump, Firmware;
        public List<string> Dlc = new List<string>();
        public List<string> Notes = new List<string>();
        public int KeysSeen, BaseSeen, UpdatesSeen;
    }

    /// <summary>one line of precheck.py: level ok | warn | bad</summary>
    public sealed class PcCheck
    {
        public string Level, What, Msg;
    }

    /// <summary>the choices on the setup page, turned into install.py's arguments</summary>
    public sealed class SetupChoice
    {
        public string Game, Update, Keys, Firmware, Location;
        public List<string> Dlc = new List<string>();
        public int Jobs;
        public bool Dry;
    }

    public static class Installer
    {
        public static string Root => Core.Repo ?? Path.GetDirectoryName(Updater.ExePath);
        public static string DefaultLocation => Path.Combine(Root, "build");

        /// <summary>the private Python (bootstrap.ps1), else the one it fell back to (build\python_path.txt)</summary>
        public static string Python
        {
            get
            {
                string p = Path.Combine(Root, @"deps\python\python.exe");
                if (File.Exists(p)) return p;
                try
                {
                    string f = Path.Combine(Root, @"build\python_path.txt");
                    string q = File.Exists(f) ? File.ReadAllLines(f).FirstOrDefault()?.Trim() : null;
                    if (!string.IsNullOrEmpty(q) && File.Exists(q)) return q;
                }
                catch { }
                return null;
            }
        }

        /// <summary>a dump folder: exefs\ and romfs\ inside, already decrypted</summary>
        public static bool IsDump(string p) =>
            !string.IsNullOrEmpty(p) && Directory.Exists(Path.Combine(p, "exefs")) && Directory.Exists(Path.Combine(p, "romfs"));

        static ProcessStartInfo Hidden(string exe, string args)
        {
            var psi = new ProcessStartInfo(exe, args)
            {
                WorkingDirectory = Root, UseShellExecute = false, CreateNoWindow = true,
                RedirectStandardOutput = true, RedirectStandardError = true,
                StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8,
            };
            psi.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";
            return psi;
        }

        /// <summary>a hidden process; every line to line() and to the log file; exited(code) at the end</summary>
        static Process Start(ProcessStartInfo psi, string log, Action<string> line, Action<int> exited)
        {
            Directory.CreateDirectory(Path.GetDirectoryName(log));
            var w = new StreamWriter(log, false, Encoding.UTF8) { AutoFlush = true };
            var p = new Process { StartInfo = psi, EnableRaisingEvents = true };
            DataReceivedEventHandler on = (s, e) =>
            {
                if (e.Data == null) return;
                lock (w) try { w.WriteLine(e.Data); } catch (ObjectDisposedException) { }
                line?.Invoke(e.Data);
            };
            p.OutputDataReceived += on;
            p.ErrorDataReceived += on;
            p.Exited += (s, e) => { p.WaitForExit(); lock (w) w.Dispose(); exited?.Invoke(p.ExitCode); };
            p.Start();
            p.BeginOutputReadLine();
            p.BeginErrorReadLine();
            return p;
        }

        /// <summary>step 1: the private Python (bootstrap.ps1 -NoLaunch: download, SHA-256 check, pip packages); nothing
        /// to do when it is already there. Blocks; returns the Python or throws.</summary>
        public static string PrepareTools(Action<string> line)
        {
            if (Python != null && File.Exists(Path.Combine(Root, @"deps\python\python.exe"))) return Python;
            var psi = Hidden("powershell.exe", "-NoProfile -ExecutionPolicy Bypass -File \"" + Path.Combine(Root, @"scripts\bootstrap.ps1") + "\" -NoLaunch");
            psi.StandardOutputEncoding = psi.StandardErrorEncoding = null;          // Windows PowerShell writes the console code page
            int code = -1;
            var done = new System.Threading.ManualResetEvent(false);
            Start(psi, Path.Combine(Root, @"build\bootstrap.log"), line, c => { code = c; done.Set(); });
            done.WaitOne();
            string py = Python;
            if (code != 0 || py == null)
                throw new InvalidOperationException("The tools could not be prepared (exit code " + code + "). See build\\bootstrap.log.");
            return py;
        }

        static string RunJson(string py, string args, int timeoutMs)
        {
            var psi = Hidden(py, args);
            using (var p = Process.Start(psi))
            {
                var err = p.StandardError.ReadToEndAsync();
                string o = p.StandardOutput.ReadToEnd();
                if (!p.WaitForExit(timeoutMs)) { try { p.Kill(); } catch { } throw new TimeoutException("timed out: " + args); }
                int i = o.IndexOfAny(new[] { '{', '[' });
                if (i < 0) throw new InvalidDataException("no result from " + args + ": " + err.Result.Trim());
                return o.Substring(i);
            }
        }

        static string S(Dictionary<string, object> d, string k) => d != null && d.TryGetValue(k, out var v) ? v as string : null;
        static int N(Dictionary<string, object> d, string k) => d != null && d.TryGetValue(k, out var v) && v is ArrayList a ? a.Count : 0;

        /// <summary>step 2a: find_inputs.py --json (only names and headers are read, no key value)</summary>
        public static Found Scan(string py)
        {
            var d = new JavaScriptSerializer { MaxJsonLength = 64 << 20 }.Deserialize<Dictionary<string, object>>(
                RunJson(py, "-u scripts\\find_inputs.py --json", 300000));
            var best = d.TryGetValue("best", out var b) ? b as Dictionary<string, object> : null;
            var f = new Found
            {
                Keys = S(best, "prod_keys"), Base = S(best, "base"), Update = S(best, "update"), Build = S(best, "build"),
                Dump = S(best, "dump"), Firmware = S(best, "firmware"),
                KeysSeen = N(d, "keys"), BaseSeen = N(d, "base"), UpdatesSeen = N(d, "updates"),
            };
            if (best != null && best.TryGetValue("dlc", out var dl) && dl is ArrayList dlc) f.Dlc = dlc.Cast<object>().Select(x => x as string).Where(x => x != null).ToList();
            if (d.TryGetValue("notes", out var nt) && nt is ArrayList notes) f.Notes = notes.Cast<object>().Select(x => x as string).Where(x => x != null).ToList();
            return f;
        }

        /// <summary>step 2b: precheck.py --json for the chosen files and install location</summary>
        public static List<PcCheck> Precheck(string py, SetupChoice c)
        {
            var a = new StringBuilder("-u scripts\\precheck.py --json --build " + Q(c.Location));
            if (IsDump(c.Game)) a.Append(" --dump " + Q(c.Game.TrimEnd('\\')));
            else foreach (var g in new[] { c.Game, c.Update }) if (!string.IsNullOrEmpty(g) && File.Exists(g)) a.Append(" --game " + Q(g));
            var list = new JavaScriptSerializer().Deserialize<ArrayList>(RunJson(py, a.ToString(), 120000));
            return list.Cast<Dictionary<string, object>>().Select(x => new PcCheck { Level = S(x, "level"), What = S(x, "what"), Msg = S(x, "msg") }).ToList();
        }

        /// <summary>one command-line argument, quoted the way CreateProcess reads it</summary>
        public static string Q(string s)
        {
            if (s == null) return "\"\"";
            var sb = new StringBuilder("\"");
            int slashes = 0;
            foreach (char ch in s)
            {
                if (ch == '\\') { slashes++; continue; }
                if (ch == '"') { sb.Append('\\', slashes * 2 + 1); sb.Append('"'); }
                else { sb.Append('\\', slashes); sb.Append(ch); }
                slashes = 0;
            }
            sb.Append('\\', slashes * 2);
            return sb.Append('"').ToString();
        }

        /// <summary>install.py's arguments for the choices (the sources are already at the release: no self-update)</summary>
        public static string Arguments(SetupChoice c)
        {
            var a = new StringBuilder("-u scripts\\install.py --no-gui --progress-json --no-self-update");
            if (IsDump(c.Game)) a.Append(" --dump " + Q(c.Game.TrimEnd('\\')));
            else
            {
                if (!string.IsNullOrEmpty(c.Game)) a.Append(" --base " + Q(c.Game));
                if (!string.IsNullOrEmpty(c.Update)) a.Append(" --update " + Q(c.Update));
                if (!string.IsNullOrEmpty(c.Keys)) a.Append(" --keys " + Q(c.Keys));
                foreach (var d in c.Dlc)
                {
                    if (a.Length + d.Length > 30000) break;          // the Windows command line holds 32767 characters
                    a.Append(" --dlc " + Q(d));
                }
            }
            if (!string.IsNullOrEmpty(c.Firmware)) a.Append(" --firmware " + Q(c.Firmware.TrimEnd('\\')));
            if (!string.IsNullOrEmpty(c.Location) && !string.Equals(Path.GetFullPath(c.Location).TrimEnd('\\'), DefaultLocation, StringComparison.OrdinalIgnoreCase))
                a.Append(" --build-dir " + Q(c.Location.TrimEnd('\\')));
            if (c.Jobs > 0) a.Append(" --jobs " + c.Jobs);
            if (c.Dry || Environment.GetEnvironmentVariable("SSBU_ARENA_SETUP_DRY") == "1") a.Append(" --dry-run");
            return a.ToString();
        }

        /// <summary>step 3: install.py, hidden; resumable (run it again after an error or a stop)</summary>
        public static Process Install(string py, SetupChoice c, Action<string> line, Action<int> exited)
        {
            string log = Path.Combine(string.IsNullOrEmpty(c.Location) ? DefaultLocation : c.Location, @"logs\installer.log");
            return Start(Hidden(py, Arguments(c)), log, line, exited);
        }

        public static string LogPath(SetupChoice c) => Path.Combine(string.IsNullOrEmpty(c.Location) ? DefaultLocation : c.Location, @"logs\installer.log");

        /// <summary>an install location already built (another drive, an earlier install, a copy from another PC): the folder
        /// itself or one with build\ inside, holding work\ssbu_native.exe and state.json. Returns it, or null.</summary>
        public static string ExistingBuild(string folder)
        {
            foreach (var d in new[] { folder, Path.Combine(folder ?? "", "build") })
                if (!string.IsNullOrEmpty(folder) && File.Exists(Path.Combine(d, @"work\ssbu_native.exe")) && File.Exists(Path.Combine(d, "state.json")))
                    return Path.GetFullPath(d).TrimEnd('\\');
            return null;
        }

        /// <summary>the unpacked game an install was built from (state.json "dump"/"romfs", or dump\romfs next to it)</summary>
        public static bool GameFilesThere(string build)
        {
            try
            {
                if (Directory.Exists(Path.Combine(build, @"..\dump\romfs"))) return true;
                var m = System.Text.RegularExpressions.Regex.Match(File.ReadAllText(Path.Combine(build, "state.json")), "\"romfs\"\\s*:\\s*\"((?:[^\"\\\\]|\\\\.)*)\"");
                string romfs = m.Success ? System.Text.RegularExpressions.Regex.Unescape(m.Groups[1].Value) : null;
                return romfs != null && (File.Exists(Path.Combine(romfs, "data.arc")) || File.Exists(Path.Combine(romfs, "data.arcp")));
            }
            catch { return false; }
        }

        /// <summary>the launcher, run.py and install.py use this install location from now on (build_location.txt, as
        /// scripts/build_location.py --set writes it; the default folder removes the file)</summary>
        public static void UseLocation(string build)
        {
            string f = Path.Combine(Root, "build_location.txt");
            if (string.Equals(Path.GetFullPath(build).TrimEnd('\\'), DefaultLocation, StringComparison.OrdinalIgnoreCase)) { if (File.Exists(f)) File.Delete(f); }
            else File.WriteAllText(f, build + "\r\n", new UTF8Encoding(false));
        }

        /// <summary>the Microsoft C++ Build Tools (install.py's error action "msvc", only without the prebuilt runtime): winget in
        /// a console the user sees</summary>
        public static void InstallBuildTools()
        {
            const string cmd = "winget install --id Microsoft.VisualStudio.2022.BuildTools -e --accept-package-agreements --accept-source-agreements --override \"--passive --wait --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended\"";
            Process.Start(new ProcessStartInfo("cmd.exe", "/k echo Installing the Microsoft C++ Build Tools (5-15 minutes)... & " + cmd +
                " & echo. & echo Finished: close this window and press Resume in SSBU Arena.") { UseShellExecute = true });
        }
    }
}
