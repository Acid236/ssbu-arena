// SPDX-License-Identifier: GPL-3.0-or-later
// SSBU Arena updates: the launcher is the only download. At every start it reads the latest GitHub Release of the
// repository (its asset arena-release.json, written by scripts/arena_release.py):
//   {"version": "0.2.0", "commit": "<40 hex>", "launcher": {"file": "SSBU-Arena.exe", "sha256": "..."}}
// - a newer launcher version: the exe is downloaded, checked against its SHA-256 and put in place of this one (the running
//   exe is renamed to .old, which Windows allows), then started again;
// - another commit than the installed one (build\update_manifest.json, scripts/update.py): scripts/install.py runs without
//   its window; it brings the sources to the release (update.py follows the latest release), takes the release's prebuilt
//   runtime (install.py RUNTIME_RELEASE, SHA-256 checked) and rebuilds here only what the change needs;
// - not installed yet (no scripts\ beside the exe): the sources of the release are unpacked beside the exe; the launcher's
//   setup screen (Installer.cs, MainWindow.Setup.cs) then prepares the tools and asks for the game files.
// A git checkout (a developer's copy) is never changed; SSBU_ARENA_UPDATE=off skips everything, =force checks a git checkout too.
// Tests: SSBU_ARENA_RELEASE=<folder> reads arena-release.json and its files from a folder instead of GitHub;
// SSBU_ARENA_UPDATE_DRY=1 runs install.py with --dry-run.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Net;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Web.Script.Serialization;

namespace Arena
{
    public sealed class Release
    {
        public string Tag, Version, Commit, LauncherUrl, LauncherSha, Page;
    }

    public static class Updater
    {
        public const string GitHubRepo = "Acid236/ssbu-arena";
        static readonly string Mode = (Environment.GetEnvironmentVariable("SSBU_ARENA_UPDATE") ?? "").ToLowerInvariant();

        static Updater() { ServicePointManager.SecurityProtocol |= SecurityProtocolType.Tls12; }

        public static Version Current => Assembly.GetExecutingAssembly().GetName().Version;
        public static string ExePath => Process.GetCurrentProcess().MainModule.FileName;
        public static bool Off => Mode == "off";
        /// <summary>a developer's git checkout: nothing is changed there unless SSBU_ARENA_UPDATE=force</summary>
        public static bool DevCopy => Core.Repo != null && Directory.Exists(Path.Combine(Core.Repo, ".git")) && Mode != "force";
        public static bool Installed => Core.Repo != null;
        static string Python => Core.Repo == null ? null : Path.Combine(Core.Repo, @"deps\python\python.exe");

        static byte[] Get(string url, string accept = null, int timeoutMs = 15000)
        {
            var rq = WebRequest.Create(url);              // https, or file:// (SSBU_ARENA_RELEASE)
            rq.Timeout = timeoutMs;
            if (rq is HttpWebRequest h)
            {
                h.UserAgent = "ssbu-arena-launcher/" + Current;
                h.ReadWriteTimeout = timeoutMs;
                if (accept != null) h.Accept = accept;
            }
            using (var rs = rq.GetResponse())
            using (var s = rs.GetResponseStream())
            using (var m = new MemoryStream()) { s.CopyTo(m); return m.ToArray(); }
        }

        /// <summary>the latest release, or null (no release with arena-release.json, offline: the launcher just goes on)</summary>
        public static Release Latest()
        {
            var js = new JavaScriptSerializer();
            string local = Environment.GetEnvironmentVariable("SSBU_ARENA_RELEASE");     // (test) a folder with arena-release.json and its files
            if (!string.IsNullOrEmpty(local))
            {
                var t = js.Deserialize<Dictionary<string, object>>(File.ReadAllText(Path.Combine(local, "arena-release.json")));
                var tl = t["launcher"] as Dictionary<string, object>;
                return new Release { Tag = "v" + t["version"], Version = t["version"] as string, Commit = t["commit"] as string, Page = local,
                                     LauncherUrl = new Uri(Path.Combine(local, (string)tl["file"])).AbsoluteUri, LauncherSha = (string)tl["sha256"] };
            }
            var rel = js.Deserialize<Dictionary<string, object>>(Encoding.UTF8.GetString(
                Get("https://api.github.com/repos/" + GitHubRepo + "/releases/latest", "application/vnd.github+json")));
            var assets = ((rel["assets"] as System.Collections.ArrayList) ?? new System.Collections.ArrayList()).Cast<Dictionary<string, object>>().ToList();
            string Url(string name) => assets.Where(a => (string)a["name"] == name).Select(a => (string)a["browser_download_url"]).FirstOrDefault();
            string info = Url("arena-release.json");
            if (info == null) return null;
            var d = js.Deserialize<Dictionary<string, object>>(Encoding.UTF8.GetString(Get(info)));
            var l = d.ContainsKey("launcher") ? d["launcher"] as Dictionary<string, object> : null;
            return new Release
            {
                Tag = rel["tag_name"] as string,
                Page = rel["html_url"] as string,
                Version = d["version"] as string,
                Commit = d["commit"] as string,
                LauncherUrl = l != null ? Url((string)l["file"]) : null,
                LauncherSha = l != null ? (string)l["sha256"] : null,
            };
        }

        public static bool LauncherOutdated(Release r) =>
            r?.LauncherUrl != null && System.Version.TryParse(r.Version, out var v) && v > Current;

        /// <summary>the commit the sources are at (scripts/update.py's manifest), null = unknown (never updated)</summary>
        public static string InstalledCommit()
        {
            try
            {
                string f = Path.Combine(Core.Repo, @"build\update_manifest.json");
                if (!File.Exists(f)) return null;
                var d = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(File.ReadAllText(f));
                return d.TryGetValue("commit", out var c) ? c as string : null;
            }
            catch { return null; }
        }

        public static bool GameOutdated(Release r) => r?.Commit != null && Installed && !DevCopy && InstalledCommit() != r.Commit;

        /// <summary>what the update check found and did, in build\launcher_update.log (the last start's only)</summary>
        public static void Log(string s)
        {
            try
            {
                string dir = Core.Repo != null ? Path.Combine(Core.Repo, "build") : Path.GetDirectoryName(ExePath);
                File.AppendAllText(Path.Combine(dir, "launcher_update.log"), DateTime.Now.ToString("HH:mm:ss ") + s + "\r\n");
            }
            catch { }
        }

        static string Sha256(byte[] b) { using (var h = SHA256.Create()) return string.Concat(h.ComputeHash(b).Select(x => x.ToString("x2"))); }

        /// <summary>leftovers of the last self-update</summary>
        public static void CleanUp()
        {
            foreach (var p in new[] { ExePath + ".old", ExePath + ".new" })
                try { if (File.Exists(p)) File.Delete(p); } catch { }
        }

        /// <summary>the new launcher in place of this exe (and of the copy in build\, if any); then it is started again</summary>
        public static void ReplaceLauncher(Release r)
        {
            byte[] exe = Get(r.LauncherUrl, null, 120000);
            if (!string.Equals(Sha256(exe), r.LauncherSha, StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("the downloaded launcher does not match its SHA-256: not used");
            string me = ExePath;
            File.WriteAllBytes(me + ".new", exe);
            if (File.Exists(me + ".old")) File.Delete(me + ".old");
            File.Move(me, me + ".old");
            File.Move(me + ".new", me);
            // the other copy: build\SSBU Arena.exe when this one is at the repository's root (setup.py link's copy)
            string other = Core.Repo != null && Path.GetDirectoryName(me).TrimEnd('\\') == Core.Repo ? Path.Combine(Core.Build, "SSBU Arena.exe") : null;
            if (other != null && File.Exists(other)) try { File.WriteAllBytes(other, exe); } catch { }
            Process.Start(new ProcessStartInfo(me, "--updated") { UseShellExecute = false });
        }

        /// <summary>scripts/install.py without its window: sources to the release, its prebuilt runtime, the rebuild it needs.
        /// line gets every output line ("##ssbu {json}" progress lines among them), exited the exit code.</summary>
        public static Process RunGameUpdate(Action<string> line, Action<int> exited)
        {
            if (!File.Exists(Python)) throw new FileNotFoundException("The private Python is missing (deps\\python): run Install SSBU.bat once.");
            string dry = Environment.GetEnvironmentVariable("SSBU_ARENA_UPDATE_DRY") == "1" ? " --dry-run" : "";      // (test) says what it would do
            var psi = new ProcessStartInfo(Python, "-u scripts\\install.py --no-gui --progress-json --no-shortcuts" + dry)
            {
                WorkingDirectory = Core.Repo, UseShellExecute = false, CreateNoWindow = true,
                RedirectStandardOutput = true, RedirectStandardError = true,
                StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8,
            };
            psi.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";
            var p = new Process { StartInfo = psi, EnableRaisingEvents = true };
            string log = Path.Combine(Core.Repo, @"build\update_last.log");
            Directory.CreateDirectory(Path.GetDirectoryName(log));
            var w = new StreamWriter(log, false, Encoding.UTF8) { AutoFlush = true };
            DataReceivedEventHandler on = (s, e) => { if (e.Data == null) return; lock (w) w.WriteLine(e.Data); line(e.Data); };
            p.OutputDataReceived += on;
            p.ErrorDataReceived += on;
            p.Exited += (s, e) => { p.WaitForExit(); lock (w) w.Dispose(); exited(p.ExitCode); };
            p.Start();
            p.BeginOutputReadLine();
            p.BeginErrorReadLine();
            return p;
        }

        public static IEnumerable<string> UpdateLogTail(int n)
        {
            try { return File.ReadAllLines(Path.Combine(Core.Repo, @"build\update_last.log")).Where(l => !l.StartsWith("##ssbu ")).Reverse().Take(n).Reverse().ToList(); }
            catch { return new List<string>(); }
        }

        /// <summary>first start of the downloaded launcher: the release's sources beside the exe (the setup screen goes on)</summary>
        public static void FirstInstall(Release r, Action<string> say)
        {
            string root = Path.GetDirectoryName(ExePath);
            say("Downloading SSBU Arena " + r.Version + "...");
            byte[] zip = Get("https://codeload.github.com/" + GitHubRepo + "/zip/" + r.Commit, null, 600000);
            say("Unpacking...");
            var files = new SortedDictionary<string, string>(StringComparer.Ordinal);
            string top = null;
            using (var z = new ZipArchive(new MemoryStream(zip)))
            {
                foreach (var e in z.Entries)
                {
                    int cut = e.FullName.IndexOf('/');
                    if (top == null && cut > 0) top = e.FullName.Substring(0, cut);
                    string rel = cut < 0 ? "" : e.FullName.Substring(cut + 1);
                    if (rel == "" || rel.EndsWith("/")) continue;
                    if (rel.Split('/').Any(p => p == ".." || p == "") || rel.Contains(":")) throw new InvalidDataException("unsafe path in the download: " + e.FullName);
                    string dst = Path.Combine(root, rel.Replace('/', '\\'));
                    Directory.CreateDirectory(Path.GetDirectoryName(dst));
                    e.ExtractToFile(dst, true);
                    files[rel] = Sha256(File.ReadAllBytes(dst));
                }
            }
            // scripts/update.py's manifest (same format): the next update knows the commit and which files are the repository's
            var manifest = new Dictionary<string, object>
            {
                ["repo"] = GitHubRepo, ["branch"] = "main", ["commit"] = r.Commit, ["zip_top"] = top,
                ["updated"] = DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss"), ["files"] = files,
            };
            Directory.CreateDirectory(Path.Combine(root, "build"));
            File.WriteAllText(Path.Combine(root, @"build\update_manifest.json"), new JavaScriptSerializer().Serialize(manifest));
        }
    }
}
