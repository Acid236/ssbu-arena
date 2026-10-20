# Linux and macOS install speed (2026-10-20, branch linuxmac-speed)

## Where the time went (Steam Deck report: 4.5 hours, 50 minutes of it self-tests)

Linux and macOS install with `scripts/setup.py --target linux|macos`; there is no prebuilt runtime there, but the
runtime is a small part of the time. Per step, on the porter's PC (24 threads, 31 GB, BUILDING_LINUX.md) and as it
scales to a Deck (Zen 2, 4 cores / 8 threads, 16 GB, about 0.6 times a desktop core):

| Step | Porter's PC | Deck before | What it is |
|---|---|---|---|
| deps .. sdk | < 1 min | a few min | checks, conversion, lifting (Python) |
| compile | ~1.5 h (4 jobs) | ~3 h (3 jobs) | 1,161 lifted C files of the game, clang -O1: **made from the dump, cannot be shipped** |
| nro | 14 min | ~30 min | 98 script modules, lifted and compiled: also from the dump |
| link | ~1 min | a few min | the runtime (our ~50 C files) + the game library |
| check | ~1 min | 50 min (hang) | self-tests; the hang is fixed on main (5c489c8, 3e7d7fe) |

The compile and nro steps are the install. Two things made them slower than they had to be:

1. **The job rule.** `default_jobs()` (setup.py) ran one compiler per 4 GB of RAM, and `build_opt.limit_memory` held each
   to (RAM - 4 GB) / jobs. A Deck's 16 GB (MemTotal about 15 GB) gave 3 compilers on 8 threads, and the nro step then
   built one module at a time (`build_nro`: modules at once = jobs // 4). Measured here with clang 9 -O1 (the Windows
   compiler; Linux uses clang 19+, which needs more): the median file peaks at 0.13 GB, the 99th percentile at 0.9 GB,
   c_013a.c (a 121,565-statement function) at 1.5 GB. Only the giant-function files go to many GB (the porter saw
   c_00a3.c, 215,493 statements, pass 12 GB in 30 s with current clang).
2. **Identical ladder retries.** A file over the 180 s limit is retried with more functions unoptimised (limit 20,000,
   then 5,000, then 1,250 statements). When no function falls between two limits the retry is the very same compile and
   times out again: c_03d9.c and c_019e.c ran three identical 180 s attempts, c_00a3.c and c_013a.c two (Windows report
   of 2026-10-19: 4 files, 540 s each, before -O0). On a slower CPU and a newer clang more files reach the limit.

## Done on this branch (Windows unchanged: everything below is behind RECOMP_TARGET linux / macos)

- `tools/lifter/build_opt.py`: the compilers share RAM - 4 GB (`MEM_BUDGET`). Each compile reserves an estimate before it
  starts (max of 1.5 GB, 0.75 GB per MB of source, 40 KB per statement of its longest function; at most the budget),
  first come first served. Linux: the reservation is the `prlimit --as` limit; a file over it is compiled again with
  twice as much, up to the budget, and only over the whole budget takes the next ladder step (as before); a file that
  ran out at the floor raises the floor by a quarter for the files after it (so a clang that needs more than 1.5 GB for
  ordinary files does not make each of them run out once). macOS: no
  limit can be enforced (no RLIMIT_AS), the reservations only pace the compilers.
- `build_opt.py`: on Linux / macOS a ladder step with the same number of unoptimised functions as the attempt that just
  failed (the same set: each limit's set holds the previous one) is skipped.
- `scripts/setup.py`: on Linux / macOS the default job count is min(24, CPU threads); the RAM rule stays for the lifters
  (`recomp_eh.py`'s worker processes, and the nro lifters through `RECOMP_LIFT_JOBS` in build_nro.py), whose memory the
  compilers' sharing does not count. A Deck: 8 compilers, 2 modules at once in nro, 3 lifter processes.
- `tests/build_opt_sched_test.py` (in both CI workflows): the scheduling with a fake compiler, for all three targets,
  including that Windows has no reservations and the unchanged ladder.
- Steam Deck: `install_deps.sh` stops on SteamOS with the distrobox recipe (`--steamos-host` to use pacman on SteamOS),
  and on a Deck adds vulkan-radeon and libpulse (a fresh Arch container has neither).

Expected on a Deck: compile and nro about 1.6 to 2 times faster (8 threads on 4 SMT cores instead of 3 compilers),
the build roughly 2 to 2.5 hours. **Not measured**: needs a tester's log (`logs/compile.log` prints the sharing line
and `_opt_report.txt` the fallbacks).

## Prebuilt Linux / macOS runtime package: designed, not implemented

On Windows the package saves the MSVC Build Tools, the Windows SDK and the runtime's compile. On Linux / macOS the
runtime's compile is minutes of a multi-hour build, so the package would mainly save **dependencies** (no -dev
packages, no SDL3 / FFmpeg / glslang headers, no Vulkan-Headers, no suyu, no Pillow / unicorn), not time. It is not
contained, for three reasons:

1. **The host exe alone does not run on Linux / macOS.** `build.py host` links it with
   `--unresolved-symbols=ignore-in-object-files` (Linux) or `-undefined dynamic_lookup` (macOS): a compile check. Nothing
   makes the loader open the game library. Windows solves this with an import library from `nocrt/ssbu_game.def`. The
   counterpart: a stub `libssbu_game_eh_o1.so` / `.dylib` made in CI from the same .def (every export as an empty
   function or a data symbol, soname / install name `@rpath/ssbu_game_eh_o1.*`), linked by the exe, replaced on the
   player's PC by the real library of the same name (rpath $ORIGIN / @executable_path is already set). Data exports
   are reached through GOT entries (-fPIC), so there are no copy relocations to size.
2. **Library ABIs differ per distribution and per Homebrew upgrade.** The exe links SDL3 (libSDL3.so.0: stable),
   FreeType (.so.6) and OpenSSL (.so.3): stable sonames. FFmpeg is not: libavcodec.so.60 (Ubuntu 24.04, FFmpeg 6),
   .61 (Arch, Debian 13, Fedora 42, FFmpeg 7), .62 (FFmpeg 8); glslang is shared on Arch / Fedora and static on Debian.
   Homebrew links by absolute path (/opt/homebrew/opt/ffmpeg/lib/libavcodec.61.dylib) and `brew upgrade` moves FFmpeg's
   major version. So the package must carry its own: an LGPL FFmpeg with only the decoders the game needs (VP9, Vorbis,
   H.264, as `scripts/ffmpeg/build_ffmpeg_win.sh` already does for Windows), glslang linked statically into the shim,
   SDL3 from its release tag; all with @rpath / $ORIGIN names. glibc: build in the oldest distribution supported (a
   Debian 12 container with clang 19 from apt.llvm.org: glibc 2.36, older than every distribution the port supports).
3. **macOS signing.** Every arm64 binary must carry a signature; changing install names (install_name_tool) needs an
   ad-hoc re-sign (`codesign -s -`). A download through a browser is quarantined and Gatekeeper refuses unsigned
   programs; the installer's own download (Python urllib, like install.py) sets no quarantine attribute, so the package
   must be fetched by the script, never by hand.

Implementation order when wanted: (a) the stub game library and a host exe that starts with the real library (test:
the CI host build, then a tester's self-test run); (b) the CI job `linux-release` / `macos-release` making
`runtime-<sha>-linux-x86_64.zip` / `-macos-arm64.zip` with the manifest of make_release.py (same tree digest rule);
(c) `setup.py --target linux --runtime <zip>` taking the Windows package path (build.py gamedll, copy, hash check) and
`deps_linux` / `deps_mac` checking only clang and the Python packages in that mode; (d) install_deps.sh /
install_mac.sh downloading it. The game library and the modules are still compiled on the player's PC: they are made
from the dump.

## Further ideas (each needs the owner's call or a measurement)

- **Time limit on slow CPUs.** 180 s per attempt was set on fast PCs; on a Deck more files reach it, fall back to less
  optimisation and lose 180 s each. A limit scaled by a short calibration compile would keep the same optimisation
  everywhere. Needs a Deck's `_opt_report.txt` first.
- **Hot / cold split.** Most of the game library's code is cold. Compiling only the files with hot functions at -O1
  and the rest at -O0 would cut compile time several times, at a cost in speed that only a 60 fps measurement can price.
  Owner's decision (the fixed 60 fps goal).
- **Shipping ladder hints** (file name -> fallback step, like build.py's SLOW_FILES) would save the first 180 s
  attempt of the few hopeless files. Names only, nothing of the game; but they depend on the lifter version and the game
  build, and the identical-retry skip already removes most of that waste.
