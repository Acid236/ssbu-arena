// SPDX-License-Identifier: GPL-3.0-or-later
// SSBU Arena launcher: Settings > Game files > Check and repair. The files the game needs are checked against
// build\files.sha256, the list install.py writes when a build is finished (scripts/verify.py: one line per file,
// "<sha256> <size> <path>", the path relative to the build folder; "romfs:data.arc" is checked by size only). A missing or
// changed file is repaired by scripts/verify.py repair (it removes the bad files and marks the setup steps that make them
// as not done) and then install.py, which remakes only those. A portable copy has no Python: it is only checked.
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;

namespace Arena
{
    public sealed class FileProblem
    {
        public string Path, Why;
        public override string ToString() => Why + ": " + Path.Replace('/', '\\');
    }

    public static class FileCheck
    {
        public static string ListPath => Path.Combine(Core.Build, "files.sha256");
        public static bool HasList => File.Exists(ListPath);
        public static bool CanRepair => Core.Repo != null && File.Exists(Path.Combine(Core.Repo, @"scripts\verify.py"));

        static readonly string[] WorkFiles = { "ssbu_native.exe", "ssbu_game_eh_o1.dll", "SDL3.dll", "ssbu_glslang.dll", "opus.dll", "libopus-0.dll",
                                               "loading_kirby.png", "arena.ico", "ssbu_native_rb.exe", "ssbu_game_r1.dll", "ssbu_ui_native.exe" };
        static readonly string[] Trees = { "work/nro_bin_eh_o2", "work/nro_bin_eh_o2r1", "work/arena_fonts", "binaries", "sysdata",
                                           "characters/arena_menu", "characters/competitive" };

        static string Full(string rel)
        {
            if (rel.StartsWith("romfs:")) return Core.RomFS == null ? null : Path.Combine(Core.RomFS, rel.Substring(6));
            return Path.Combine(Core.Build, rel.Replace('/', '\\'));
        }

        static string Sha256(string file)
        {
            using (var s = File.OpenRead(file))
            using (var h = SHA256.Create())
                return string.Concat(h.ComputeHash(s).Select(b => b.ToString("x2")));
        }

        /// <summary>each file of the list: missing or changed (quick: by size only); progress(done, total)</summary>
        public static List<FileProblem> Check(bool quick, Action<int, int> progress)
        {
            var lines = File.ReadAllLines(ListPath).Where(l => l.Length > 0 && l[0] != '#').ToList();
            var bad = new List<FileProblem>();
            for (int i = 0; i < lines.Count; i++)
            {
                progress?.Invoke(i, lines.Count);
                var p = lines[i].Split(new[] { ' ' }, 3);
                if (p.Length < 3) continue;
                string f = Full(p[2]);
                if (f == null || !File.Exists(f)) bad.Add(new FileProblem { Path = p[2], Why = "missing" });
                else if (new FileInfo(f).Length != long.Parse(p[1]) || (!quick && p[0] != "-" && Sha256(f) != p[0]))
                    bad.Add(new FileProblem { Path = p[2], Why = "damaged" });
            }
            progress?.Invoke(lines.Count, lines.Count);
            return bad;
        }

        /// <summary>the list from the files as they are now (an install from before the list existed, or a portable copy):
        /// they are taken as good. Returns how many files.</summary>
        public static int Write()
        {
            var rels = new List<string>();
            string work = Path.Combine(Core.Build, "work");
            foreach (var n in WorkFiles) if (File.Exists(Path.Combine(work, n))) rels.Add("work/" + n);
            if (Directory.Exists(work))
                rels.AddRange(Directory.GetFiles(work, "*.dll").Select(Path.GetFileName)
                    .Where(n => System.Text.RegularExpressions.Regex.IsMatch(n, @"^(av|sw)\w*-\d+\.dll$", System.Text.RegularExpressions.RegexOptions.IgnoreCase))
                    .OrderBy(n => n, StringComparer.Ordinal).Select(n => "work/" + n));
            foreach (var t in Trees)
            {
                string root = Path.Combine(Core.Build, t.Replace('/', '\\'));
                if (!Directory.Exists(root)) continue;
                foreach (var f in Directory.GetFiles(root, "*", SearchOption.AllDirectories).OrderBy(x => x, StringComparer.Ordinal))
                {
                    if (t.StartsWith("work/nro_bin") && !f.EndsWith(".dll", StringComparison.OrdinalIgnoreCase)) continue;
                    rels.Add(f.Substring(Core.Build.Length + 1).Replace('\\', '/'));
                }
            }
            var sb = new StringBuilder("# SSBU Arena: the files of this install (launcher). <sha256> <size> <path>\n");
            foreach (var r in rels)
            {
                string f = Full(r);
                sb.Append(Sha256(f)).Append(' ').Append(new FileInfo(f).Length).Append(' ').Append(r).Append('\n');
            }
            string arc = Core.RomFS == null ? null : Path.Combine(Core.RomFS, "data.arc");
            if (arc != null && File.Exists(arc)) { sb.Append("- ").Append(new FileInfo(arc).Length).Append(" romfs:data.arc\n"); rels.Add("arc"); }
            File.WriteAllText(ListPath, sb.ToString(), new UTF8Encoding(false));
            return rels.Count;
        }
    }
}
