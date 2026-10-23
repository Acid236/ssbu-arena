// SPDX-License-Identifier: GPL-3.0-or-later
// SSBU Arena launcher: what the old Launcher.ps1 did, without the window. Paths of the build, the settings files
// (config\launcher.ini, account.txt, dlc.txt and some keys of graphics.ini and controllers.ini), the checks before a
// match, the controllers the game sees, saves and DLC, and starting the game with the online environment.
// The exe lives in build\ next to work\ and config\ (scripts\setup.py link copies it there); in the portable copy too.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;

namespace Arena
{
    public sealed class Check
    {
        public bool Ok;
        public string Text;
        public Check(bool ok, string text) { Ok = ok; Text = text; }
    }

    public sealed class Pad
    {
        public string Guid, Name;
        public Pad(string guid, string name) { Guid = guid; Name = name; }
    }

    public static class Core
    {
        public const string DefaultServer = "eu-germany.ssbuarena.com:39010";      // our lobby (tools/net/rb_lobby.c, relay only)
        /// <summary>the Arena servers the player picks from (Settings > Online), by region: relay only, never another
        /// player's address</summary>
        public static readonly (string Name, string Address)[] Servers = { ("Europe", DefaultServer) };
        /// <summary>a saved server -> its place in Servers (an address no longer offered: the first one)</summary>
        public static int ServerIndex(string address)
        {
            for (int i = 0; i < Servers.Length; i++) if (string.Equals(Servers[i].Address, (address ?? "").Trim(), StringComparison.OrdinalIgnoreCase)) return i;
            return 0;
        }
        public const string Site = "https://ssbuarena.com/";

        // the exe at the repository's root (the downloaded launcher after its first install) or in its build\ folder (setup.py
        // link); Repo null = not installed yet (Updater.cs installs into the exe's folder)
        static readonly string ExeDir = AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\');
        public static readonly string Repo = FindRepo();
        public static readonly string Build = FindBuild();
        public static readonly string Work = Path.Combine(Build, "work");
        public static readonly string Cfg = Path.Combine(Build, "config");
        public static readonly string Exe = Path.Combine(Work, "ssbu_native.exe");
        public static readonly string RbExe = Path.Combine(Work, "ssbu_native_rb.exe");
        public static readonly string UiExe = Path.Combine(Work, "ssbu_ui_native.exe");
        public static readonly string MainElf = Path.Combine(Build, @"binaries\13.0.4\main.elf");
        public static readonly string Fonts = Path.Combine(Build, @"sysdata\fonts");
        public static readonly string GameLog = Path.Combine(Build, "game.log");
        static readonly string LauncherIni = Path.Combine(Cfg, "launcher.ini");
        static readonly string OnlineIni = Path.Combine(Cfg, "online.ini");
        static readonly string GfxIni = Path.Combine(Cfg, "graphics.ini");
        static readonly string PadIni = Path.Combine(Cfg, "controllers.ini");
        static readonly string DlcFile = Path.Combine(Cfg, "dlc.txt");
        static readonly string CompDir = Path.Combine(Build, @"characters\competitive");

        public static readonly bool Portable = Directory.Exists(Path.Combine(Build, @"..\dump\romfs"));
        public static string RomFS;
        public static bool HasOnline, RbPair, HasCompetitive, LightArc;

        // settings (launcher.ini and the game's ini files)
        public static string Nickname = "", Server = DefaultServer, Code = "", Saves;
        public static bool Online, Rollback = true, Ping = true, Competitive = true;
        public static string ShaderStamp = "";
        public static string Ticket;                // the lobby ticket of this start (Account.LobbyTicket), signed in only      // launcher.ini shaders: what the last preparation was made for (ShaderKey)
        public static int Aspect, WindowMode, Keyboard;
        public static string WindowSize = "1280x720";
        public static string Player1 = "auto", Player2 = "auto";

        static string FindRepo()
        {
            if (File.Exists(Path.Combine(ExeDir, @"scripts\setup.py"))) return ExeDir;
            string up = Path.GetDirectoryName(ExeDir);
            return up != null && File.Exists(Path.Combine(up, @"scripts\setup.py")) ? up : null;
        }

        static string FindBuild()
        {
            if (Repo != ExeDir) return ExeDir;
            try
            {
                // build_location.txt (scripts/build_location.py): the install location chosen in the installer window
                string f = Path.Combine(Repo, "build_location.txt");
                string line = File.Exists(f) ? File.ReadAllLines(f).FirstOrDefault()?.Trim().Trim('"') : null;
                if (!string.IsNullOrEmpty(line)) return Path.GetFullPath(Environment.ExpandEnvironmentVariables(line));
            }
            catch { }
            return Path.Combine(Repo, "build");
        }

        public static void Load()
        {
            Directory.CreateDirectory(Cfg);
            if (Portable) RomFS = Path.GetFullPath(Path.Combine(Build, @"..\dump\romfs"));
            else
            {
                string st = Path.Combine(Build, "state.json");
                if (File.Exists(st))
                {
                    // "dump": {..., "romfs": "C:\\..."}: the only key the launcher needs, read without a JSON library
                    var m = Regex.Match(File.ReadAllText(st), "\"romfs\"\\s*:\\s*\"((?:[^\"\\\\]|\\\\.)*)\"");
                    if (m.Success) RomFS = Regex.Unescape(m.Groups[1].Value);
                }
            }
            HasOnline = File.Exists(Exe) && File.ReadAllText(Exe, Encoding.ASCII).Contains("SSBU_ONLINE");
            // the rollback build: game DLL and script modules with dirty-page marks (setup.py step rollback); online rollback
            // runs only with it (the normal build's save is not complete enough: the two games drift apart)
            RbPair = File.Exists(RbExe) && File.Exists(Path.Combine(Work, "ssbu_game_r1.dll")) && File.Exists(Path.Combine(Work, @"nro_bin_eh_o2r1\lua2cpp_common.dll"));
            HasCompetitive = Directory.Exists(CompDir);
            LightArc = RomFS != null && File.Exists(Path.Combine(RomFS, "data.arcp")) && !File.Exists(Path.Combine(RomFS, "data.arc"));

            var L = ReadIni(LauncherIni);
            var O = ReadIni(OnlineIni);
            string defSaves = Portable ? Path.Combine(Path.GetDirectoryName(Build), "saves") : Path.Combine(Build, "saves");
            Saves = Get(L, "saves") ?? defSaves;
            Nickname = Get(O, "nickname") ?? Get(L, "nickname") ?? "";
            Online = L.ContainsKey("online") ? L["online"] == "on" : (Get(O, "server") != null && Get(O, "room") != null);
            Server = Servers[ServerIndex(Get(L, "server") ?? DefaultServer)].Address;
            Code = Get(L, "code") ?? Get(O, "room") ?? "";
            Rollback = Get(L, "rollback") != "off";
            Ping = Get(L, "ping") != "off";
            ShaderStamp = Get(L, "shaders") ?? "";
            Competitive = LightArc || (HasCompetitive && Get(L, "competitive") != "off");
            if (!HasOnline) Online = false;
            foreach (var old in new[] { "online.ini.off", "online.ini.old" })      // an older launcher's settings: code and name
            {
                string p = Path.Combine(Cfg, old);
                if (L.ContainsKey("code") || Code != "" || !File.Exists(p)) continue;
                var o2 = ReadIni(p);
                if (Get(o2, "room") != null) Code = o2["room"];
                if (Nickname == "" && Get(o2, "nickname") != null) Nickname = o2["nickname"];
            }

            var G = ReadIni(GfxIni);
            Aspect = Get(G, "aspect") == "stretch" ? 1 : 0;
            WindowMode = Get(G, "window") == "borderless" ? 1 : Get(G, "window") == "fullscreen" ? 2 : 0;
            if (Get(G, "width") != null && Get(G, "height") != null) WindowSize = G["width"] + "x" + G["height"];
            var P = ReadIni(PadIni);
            Player1 = (Get(P, "player1") ?? "auto").ToLowerInvariant();
            Player2 = (Get(P, "player2") ?? "auto").ToLowerInvariant();
            string kb = Get(P, "player");
            Keyboard = kb == "1" ? 1 : kb == "2" ? 2 : kb == "none" ? 3 : 0;
        }

        public static void Save()
        {
            string n = Nickname.Trim();
            // the console account id the game uses (nnfs.c): from the Arena account when signed in (the same on every PC)
            if (Online && HasOnline && Account.SignedIn) File.WriteAllText(Path.Combine(Cfg, "account.txt"), UidFromName("arena:" + Account.Me.Id) + "\r\n", Encoding.ASCII);
            else if (Online && HasOnline && n != "") File.WriteAllText(Path.Combine(Cfg, "account.txt"), UidFromName(n) + "\r\n", Encoding.ASCII);
            // the old local wireless online (online.ini, a server that is gone) is never used again: kept aside
            if (File.Exists(OnlineIni))
            {
                string old = Path.Combine(Cfg, "online.ini.old");
                if (File.Exists(old)) File.Delete(old);
                File.Move(OnlineIni, old);
            }
            File.WriteAllLines(LauncherIni, new[] {
                "# written by the launcher", "saves = " + Saves, "nickname = " + n,
                "competitive = " + (Competitive ? "on" : "off"), "online = " + (Online ? "on" : "off"),
                "server = " + Server.Trim(), "code = " + Code.Trim(),
                "rollback = " + (Rollback ? "on" : "off"), "ping = " + (Ping ? "on" : "off"), "shaders = " + ShaderStamp }, Encoding.ASCII);
            var gfx = new Dictionary<string, string> {
                { "aspect", Aspect == 1 ? "stretch" : "keep" },
                { "window", new[] { "windowed", "borderless", "fullscreen" }[Math.Max(0, Math.Min(2, WindowMode))] },
                { "latency", "normal" } };      // input latency: always normal (the option is gone)
            var m = Regex.Match(WindowSize.Trim(), @"^(\d{3,5})\s*[xX*]\s*(\d{3,5})$");
            if (m.Success) { gfx["width"] = m.Groups[1].Value; gfx["height"] = m.Groups[2].Value; }
            SetIniValues(GfxIni, null, gfx);
            SetIniValues(PadIni, "players", new Dictionary<string, string> { { "player1", Player1 }, { "player2", Player2 } });
            SetIniValues(PadIni, "keyboard", new Dictionary<string, string> { { "player", new[] { "auto", "1", "2", "none" }[Math.Max(0, Math.Min(3, Keyboard))] } });
        }

        static string Get(Dictionary<string, string> h, string k) { return h.TryGetValue(k, out var v) && v != "" ? v : null; }

        public static Dictionary<string, string> ReadIni(string path)
        {
            var h = new Dictionary<string, string>();
            if (!File.Exists(path)) return h;
            foreach (var l in File.ReadAllLines(path))
            {
                if (Regex.IsMatch(l, @"^\s*[#;]")) continue;
                var m = Regex.Match(l, @"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$");
                if (m.Success) h[m.Groups[1].Value.ToLowerInvariant()] = m.Groups[2].Value;
            }
            return h;
        }

        // ini files of the game: change some keys, keep everything else (comments, other sections) as it is
        static void SetIniValues(string path, string section, Dictionary<string, string> vals)
        {
            var lines = File.Exists(path) ? File.ReadAllLines(path) : new string[0];
            var outl = new List<string>();
            var left = vals.ToDictionary(kv => kv.Key.ToLowerInvariant(), kv => kv.Value);
            bool inTarget = section == null, seen = section == null;
            foreach (var l in lines)
            {
                var h = Regex.Match(l, @"^\s*\[(.+?)\]\s*$");
                if (section != null && h.Success)
                {
                    if (inTarget) { foreach (var kv in left) outl.Add(kv.Key + " = " + kv.Value); left.Clear(); }
                    inTarget = string.Equals(h.Groups[1].Value.Trim(), section, StringComparison.OrdinalIgnoreCase);
                    if (inTarget) seen = true;
                }
                else if (inTarget && !Regex.IsMatch(l, @"^\s*[#;]"))
                {
                    var k = Regex.Match(l, @"^\s*([A-Za-z0-9_.]+)\s*=");
                    if (k.Success && left.ContainsKey(k.Groups[1].Value.ToLowerInvariant()))
                    {
                        string key = k.Groups[1].Value.ToLowerInvariant();
                        outl.Add(k.Groups[1].Value + " = " + left[key]); left.Remove(key); continue;
                    }
                }
                outl.Add(l);
            }
            if (left.Count > 0)
            {
                if (!seen) { outl.Add(""); outl.Add("[" + section + "]"); }
                foreach (var kv in left) outl.Add(kv.Key + " = " + kv.Value);
            }
            File.WriteAllLines(path, outl, Encoding.ASCII);
        }

        // the account id from the name: the same name always gives the same id (two players must use two names)
        public static string UidFromName(string name)
        {
            using (var sha = SHA256.Create())
            {
                var b = sha.ComputeHash(Encoding.UTF8.GetBytes("ssbu-recomp account id|" + name));
                return string.Concat(b.Take(16).Select(x => x.ToString("x2")));
            }
        }

        /// <summary>the short tag shown under the name: four digits of the account id</summary>
        public static string Tag(string name)
        {
            if (name.Trim() == "") return "ARENA#----";
            string u = UidFromName(name.Trim());
            return "ARENA#" + (Convert.ToUInt32(u.Substring(0, 8), 16) % 10000).ToString("0000");
        }

        public static bool GameRunning()
        {
            return Process.GetProcessesByName("ssbu_native").Length + Process.GetProcessesByName("ssbu_native_rb").Length
                + Process.GetProcessesByName("ssbu_ui_native").Length > 0;
        }

        // ---------------------------------------------------------------- checks
        /// <summary>the game's files and what Windows must have; slow parts (store packages) included</summary>
        public static List<Check> CheckFiles(out List<string> missingCodecs)
        {
            var r = new List<Check>();
            missingCodecs = new List<string>();
            foreach (var x in new[] { new[] { Exe, "Game executable" }, new[] { Path.Combine(Work, "ssbu_game_eh_o1.dll"), "Game code" }, new[] { MainElf, "main.elf" } })
                r.Add(File.Exists(x[0]) ? new Check(true, x[1]) : new Check(false, x[1] + " missing: " + x[0]));
            int mods = Directory.Exists(Path.Combine(Work, "nro_bin_eh_o2")) ? Directory.GetFiles(Path.Combine(Work, "nro_bin_eh_o2"), "*.dll").Length : 0;
            r.Add(new Check(mods >= 98, "Fighter modules: " + mods + " of 98"));
            bool arc = RomFS != null && (File.Exists(Path.Combine(RomFS, "data.arc")) || File.Exists(Path.Combine(RomFS, "data.arcp")));
            r.Add(new Check(arc, arc ? "Game data (" + (LightArc ? "light archive" : "data.arc") + ")" : "data.arc not found (RomFS of the dump)"));
            bool vk = File.Exists(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), "vulkan-1.dll"));
            r.Add(new Check(vk, vk ? "Vulkan" : "Vulkan not found: update the graphics driver"));
            // the opening movie needs these two store packages (without them: a black screen)
            var have = AppxPackages(new[] { "Microsoft.WebMediaExtensions", "Microsoft.VP9VideoExtensions" });
            foreach (var c in new[] { new[] { "Microsoft.WebMediaExtensions", "Web Media Extensions", "9N5TDP8VCMHS" }, new[] { "Microsoft.VP9VideoExtensions", "VP9 Video Extensions", "9N4D0MSMP0PT" } })
            {
                if (have == null || have.Contains(c[0])) r.Add(new Check(true, c[1]));
                else { r.Add(new Check(false, c[1] + " missing (needed by the opening movie)")); missingCodecs.Add(c[2] + "|" + c[1]); }
            }
            return r;
        }

        /// <summary>the settings that must be right before going online; empty = fine</summary>
        public static List<string> CheckOnline()
        {
            var bad = new List<string>();
            if (!Online) return bad;
            string code = Code.Trim();
            if (!Account.SignedIn) bad.Add("Online play needs your SSBU Arena account: sign in (Settings > Player), or turn online off");
            if (!Regex.IsMatch(Server.Trim(), @"^[^\s:]+:\d+$")) bad.Add("Online: server must be address:port");
            if (Regex.IsMatch(code, @"\s")) bad.Add("Online: the friend code cannot have spaces");
            else if (Encoding.UTF8.GetByteCount(code) > 31) bad.Add("Online: friend code too long (31 at most)");
            return bad;
        }

        static HashSet<string> AppxPackages(string[] names)
        {
            try
            {
                // Get-AppxPackage takes one name; "ok" at the end tells an empty answer from a failed one
                string list = string.Join(",", names.Select(n => "'" + n + "'"));
                var psi = new ProcessStartInfo("powershell.exe", "-NoProfile -NonInteractive -Command \"foreach ($n in " + list + ") { Get-AppxPackage $n | ForEach-Object Name }; 'ok'\"")
                { UseShellExecute = false, RedirectStandardOutput = true, CreateNoWindow = true };
                using (var p = Process.Start(psi))
                {
                    string o = p.StandardOutput.ReadToEnd();
                    p.WaitForExit(15000);
                    var lines = o.Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries).Select(s => s.Trim()).ToList();
                    return lines.Contains("ok") ? new HashSet<string>(lines) : null;
                }
            }
            catch { return null; }      // cannot ask: do not block the game for it
        }

        public static void InstallCodec(string storeId)
        {
            try
            {
                var psi = new ProcessStartInfo("winget", "install --id " + storeId + " --source msstore --accept-package-agreements --accept-source-agreements")
                { UseShellExecute = false, CreateNoWindow = true };
                using (var p = Process.Start(psi)) p.WaitForExit(300000);
            }
            catch { Process.Start("ms-windows-store://pdp/?ProductId=" + storeId); }
        }

        // ---------------------------------------------------------------- controllers
        /// <summary>the game's own view (SDL): ssbu_native.exe --pad-list prints "pad TAB GUID TAB name" per device</summary>
        public static List<Pad> ListPads()
        {
            var pads = new List<Pad>();
            if (!File.Exists(Exe)) return pads;
            try
            {
                var psi = new ProcessStartInfo(Exe, "--pad-list") { WorkingDirectory = Work, UseShellExecute = false, RedirectStandardOutput = true, CreateNoWindow = true };
                using (var p = Process.Start(psi))
                {
                    string text = p.StandardOutput.ReadToEnd();
                    p.WaitForExit(10000);
                    foreach (var l in text.Split('\n'))
                    {
                        var c = l.TrimEnd('\r').Split('\t');
                        if (c.Length >= 3 && c[0] == "pad") pads.Add(new Pad(c[1].ToLowerInvariant(), c[2]));
                    }
                }
            }
            catch { }
            return pads;
        }

        [StructLayout(LayoutKind.Sequential)]
        struct XInputState { public uint Packet; public ushort Buttons; public byte LT, RT; public short LX, LY, RX, RY; }
        [DllImport("xinput1_4.dll", EntryPoint = "XInputGetState")] static extern int XInputGetState(int user, out XInputState s);

        /// <summary>XInput pads connected now (cheap: polled for the home page; other pads come from --pad-list)</summary>
        public static int XInputCount()
        {
            int n = 0;
            try { for (int i = 0; i < 4; i++) if (XInputGetState(i, out _) == 0) n++; } catch { }
            return n;
        }

        // ---------------------------------------------------------------- saves and DLC
        public static bool HasSave() { return File.Exists(Path.Combine(Saves, @"save\save_data\system_data.bin")); }

        /// <summary>from: a folder holding save_data\ (or the files of save_data themselves); returns a message</summary>
        public static string ImportSave(string from)
        {
            string src = File.Exists(Path.Combine(from, @"save_data\system_data.bin")) ? Path.Combine(from, "save_data")
                       : File.Exists(Path.Combine(from, "system_data.bin")) ? from : null;
            if (src == null) return "There is no Smash save in that folder (system_data.bin is missing).";
            if (GameRunning()) return "Close the game before importing a save.";
            string dst = Path.Combine(Saves, "save"), bak = null;
            if (Directory.Exists(dst))
            {
                bak = Path.Combine(Saves, "save-backup-" + DateTime.Now.ToString("yyyyMMdd-HHmmss"));
                Directory.Move(dst, bak);
            }
            CopyDir(src, Path.Combine(dst, "save_data"));
            foreach (var d in Directory.Exists(Saves) ? Directory.GetDirectories(Saves, "save.work.*") : new string[0])
                Directory.Delete(d, true);
            return "Save imported." + (bak != null ? " The previous one is in " + bak : "");
        }

        static void CopyDir(string from, string to)
        {
            Directory.CreateDirectory(to);
            foreach (var f in Directory.GetFiles(from)) File.Copy(f, Path.Combine(to, Path.GetFileName(f)), true);
            foreach (var d in Directory.GetDirectories(from)) CopyDir(d, Path.Combine(to, Path.GetFileName(d)));
        }

        /// <summary>the newest Smash save of Ryujinx (its ExtraData0 starts with the title id), or null</summary>
        public static string FindRyujinxSave()
        {
            string root = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), @"Ryujinx\bis\user\save");
            if (!Directory.Exists(root)) return null;
            string found = null;
            var sig = new byte[] { 0, 224, 22, 0, 128, 106, 0, 1 };
            foreach (var d in Directory.GetDirectories(root))
            {
                string x = Path.Combine(d, "ExtraData0");
                if (!File.Exists(x)) continue;
                var b = File.ReadAllBytes(x);
                if (b.Length < 8 || !b.Take(8).SequenceEqual(sig)) continue;
                var c = new[] { "0", "1" }.Select(s => Path.Combine(d, s)).Where(s => File.Exists(Path.Combine(s, @"save_data\system_data.bin")))
                        .OrderByDescending(s => File.GetLastWriteTime(Path.Combine(s, @"save_data\system_data.bin"))).FirstOrDefault();
                if (c != null) found = c;
            }
            return found;
        }

        public static int DlcCount()
        {
            if (!File.Exists(DlcFile)) return 0;
            return File.ReadAllLines(DlcFile).Count(l => Regex.IsMatch(l, @"^\s*0x[0-9a-fA-F]+|^\s*[0-9]+"));
        }

        /// <summary>the add-on contents owned, from the file names of the player's own DLC dumps; returns how many</summary>
        public static int ActivateDlc(string folder)
        {
            var rows = new SortedDictionary<int, string>();
            foreach (var f in Directory.EnumerateFiles(folder, "*", SearchOption.AllDirectories))
                foreach (Match m in Regex.Matches(Path.GetFileName(f), @"\[([0-9A-Fa-f]{16})\]"))
                {
                    long idx = (long)(Convert.ToUInt64(m.Groups[1].Value, 16) - 0x01006A800016E000UL) - 0x1000;
                    if (idx > 0 && idx < 0x1000) rows[(int)idx] = Path.GetFileNameWithoutExtension(f);
                }
            if (rows.Count == 0) return 0;
            var outl = new List<string> { "# add-on contents owned; written by the launcher from the file names of the player's own DLC dumps" };
            foreach (var kv in rows) outl.Add(string.Format("0x{0:x3}   # {1}", kv.Key, kv.Value));
            File.WriteAllLines(DlcFile, outl, Encoding.ASCII);
            return rows.Count;
        }

        public static void ClearDlc() { if (File.Exists(DlcFile)) File.Delete(DlcFile); }

        // ---------------------------------------------------------------- the game
        /// <summary>no preparation marker yet (the game writes one per GPU, driver and translator version): the shaders
        /// are not prepared on this PC. A new driver or game version makes a new marker name: then the game prepares them
        /// itself at its first start, as before.</summary>
        public static bool FirstRun() { return !Directory.Exists(VkCache) || Directory.GetFiles(VkCache, "prepared_*.txt").Length == 0; }

        /// <summary>the game's shader cache folder (runtime vkc_dir: SSBU_VK_CACHE, relative to work\, else build\cache\vk)</summary>
        public static string VkCache
        {
            get { string e = Environment.GetEnvironmentVariable("SSBU_VK_CACHE"); return !string.IsNullOrEmpty(e) ? Path.GetFullPath(Path.Combine(Work, e)) : Path.Combine(Build, @"cache\vk"); }
        }

        /// <summary>what a preparation is valid for: the game's exe (a new version may translate shaders differently: the
        /// marker's name then changes) and the graphics drivers (the marker and the pipeline cache are per driver)</summary>
        public static string ShaderKey()
        {
            string k = "";
            try { var fi = new FileInfo(Exe); k = fi.Length + "-" + fi.LastWriteTimeUtc.Ticks; } catch { }
            try
            {
                using (var q = new System.Management.ManagementObjectSearcher("SELECT DriverVersion FROM Win32_VideoController"))
                    foreach (var o in q.Get()) k += "-" + o["DriverVersion"];
            }
            catch { }
            return k;
        }

        /// <summary>the preparation should run before a match: never made, or made for another exe or driver (a run with
        /// nothing to do ends in a few seconds with "already")</summary>
        public static bool NeedsPrepare() { return FirstRun() || ShaderStamp != ShaderKey(); }

        static string PrepExe()
        {
            string exe = Environment.GetEnvironmentVariable("SSBU_ARENA_PREP_EXE");
            return !string.IsNullOrEmpty(exe) ? Path.Combine(Work, exe) : Exe;
        }

        static int canPrepare = -1;
        /// <summary>the game's exe knows SSBU_PREPARE_ONLY (an older one would boot hidden and never end): else the game
        /// prepares its shaders itself at its first start, as before</summary>
        public static bool CanPrepare()
        {
            if (canPrepare < 0)
                try { canPrepare = File.Exists(PrepExe()) && File.ReadAllText(PrepExe(), Encoding.ASCII).Contains("SSBU_PREPARE_ONLY") ? 1 : 0; } catch { canPrepare = 0; }
            return canPrepare == 1;
        }

        /// <summary>what every start of the game gets, a match or the shader preparation</summary>
        static void GameEnv(System.Collections.Specialized.StringDictionary env)
        {
            foreach (var v in new[] { "SSBU_ONLINE", "SSBU_ONLINE_CODE", "SSBU_ONLINE_NAME", "SSBU_ONLINE_DIRECT", "SSBU_NICKNAME", "SSBU_RB_NET", "SSBU_R1_GAMEDLL", "SSBU_NRO_BIN", "SSBU_NET_PING", "SSBU_COMPETITIVE_UI",
                                      "SSBU_PREPARE_ONLY", "SSBU_SHOW", "SSBU_ONLINE_TICKET" })
                env.Remove(v);
            env["SSBU_ROMFS"] = RomFS ?? "";
            env["SSBU_USERDATA"] = Saves;
            env["SSBU_FONTS"] = Fonts;
            env["SSBU_LOOSE_FILES"] = Competitive ? "1" : "0";      // build\characters\competitive (runtime/loose_files.c)
            env["SSBU_LATENCY"] = "normal";                          // wins over a latency = low / lowest written by hand in graphics.ini
            env["SSBU_COMPETITIVE"] = env["SSBU_LOOSE_FILES"];       // no FS meter, no random items (runtime/competitive.c)
        }

        /// <summary>the shader preparation without the game's window (runtime/nvn_vk_draw.c, SSBU_PREPARE_ONLY): the game
        /// boots hidden, prepares as on a first start, prints "##prep {json}" lines and ends once the pipeline cache and the
        /// marker are written. Every line also goes to build\prepare.log. SSBU_ARENA_PREP_EXE names another exe (tests).</summary>
        public static Process StartPrepare(Action<string> line, Action<int> exited)
        {
            Directory.CreateDirectory(Path.Combine(Build, "cache"));
            var psi = new ProcessStartInfo(PrepExe(), "\"" + MainElf + "\" 0") { WorkingDirectory = Work, UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = true, RedirectStandardError = true };
            var env = psi.EnvironmentVariables;
            GameEnv(env);
            env["SSBU_ONLINE"] = "off";
            env["SSBU_SHOW"] = "0";
            env["SSBU_PREPARE_ONLY"] = "1";
            var log = new StreamWriter(Path.Combine(Build, "prepare.log"), false, new UTF8Encoding(false)) { AutoFlush = true };
            var p = new Process { StartInfo = psi };
            DataReceivedEventHandler h = (s, e) => { if (e.Data == null) return; lock (log) { try { log.WriteLine(e.Data); } catch { } } line(e.Data); };
            p.OutputDataReceived += h;
            p.ErrorDataReceived += h;
            p.Start();
            p.BeginOutputReadLine();
            p.BeginErrorReadLine();
            System.Threading.Tasks.Task.Run(() =>
            {
                p.WaitForExit();                    // without a timeout: also waits for the last output lines
                int code = -1;
                try { code = p.ExitCode; } catch { }
                lock (log) { try { log.Dispose(); } catch { } }
                exited(code);
            });
            return p;
        }

        /// <summary>starts the game with the environment of the settings; its output goes to game.log through a hidden
        /// cmd.exe (whose exit code is the game's)</summary>
        public static Process Launch()
        {
            Directory.CreateDirectory(Saves);
            Directory.CreateDirectory(Path.Combine(Build, "cache"));
            var psi = new ProcessStartInfo(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), "cmd.exe")) { WorkingDirectory = Work, UseShellExecute = false, CreateNoWindow = true };
            var env = psi.EnvironmentVariables;
            GameEnv(env);
            env["SSBU_SHOW"] = "1";          // the window, whatever the exe is called (display.c shows it by default only for some names)
            string run = Exe;
            // online through the lobby server (runtime/net_relay.c), relay only; rollback (runtime/rb_net.c) in Smash > Versus
            if (Online && HasOnline && Account.SignedIn)
            {
                string n = Account.Me.Username, code = Code.Trim();
                env["SSBU_ONLINE_TICKET"] = Ticket ?? "";              // the lobby takes the player's name from it (rb_lobby.c)
                env["SSBU_ONLINE"] = Server.Trim();
                env["SSBU_ONLINE_NAME"] = n;
                env["SSBU_NICKNAME"] = n;
                env["SSBU_ONLINE_CODE"] = code != "" ? code : "public";
                env["SSBU_ONLINE_DIRECT"] = "0";                     // never a direct path: no player sees another one's address
                env["SSBU_NET_PING"] = Ping ? "1" : "0";             // each player's ping to the server (nvn_vk_draw.c)
                if (Rollback && RbPair)      // only with the marked pair: the normal build's rollback drifts apart (the game's own netcode then)
                {
                    env["SSBU_RB_NET"] = "net";
                    run = RbExe; env["SSBU_R1_GAMEDLL"] = "ssbu_game_r1.dll"; env["SSBU_NRO_BIN"] = "nro_bin_eh_o2r1";
                }
            }
            else env["SSBU_ONLINE"] = "off";
            // Arena's native menu uses the same game DLL (including the rollback pair selected above).
            // Keep the original hosts available when the optional menu override has not been prepared.
            if (Competitive && Directory.Exists(Path.Combine(Build, @"characters\arena_menu")))
            {
                if (run == Exe && File.Exists(UiExe)) run = UiExe;      // (the same exe: an older install's copy; the game exe otherwise)
                env["SSBU_COMPETITIVE_UI"] = "1";
                env["SSBU_MENU"] = "1"; // the Settings tile opens the existing PC settings overlay
            }
            psi.Arguments = "/d /c \"\"" + run + "\" \"" + MainElf + "\" 0 > \"" + GameLog + "\" 2>&1\"";
            var p = Process.Start(psi);
            p.EnableRaisingEvents = true;
            return p;
        }

        public static string[] PrepareLogTail(int n) { return LogTail(n, Path.Combine(Build, "prepare.log")); }

        public static string[] LogTail(int n, string file = null)
        {
            try
            {
                using (var fs = new FileStream(file ?? GameLog, FileMode.Open, FileAccess.Read, FileShare.ReadWrite))
                using (var sr = new StreamReader(fs))
                {
                    var all = sr.ReadToEnd().Split('\n').Select(l => l.TrimEnd('\r')).Where(l => l != "").ToArray();
                    return all.Skip(Math.Max(0, all.Length - n)).ToArray();
                }
            }
            catch { return new string[0]; }
        }

        public static void Open(string what)
        {
            try { Process.Start(new ProcessStartInfo(what) { UseShellExecute = true }); } catch { }
        }
    }
}
