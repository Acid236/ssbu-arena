# Building and running on a Mac (first test)

A native build for Apple Silicon Macs: the game becomes a macOS program, with SDL3 for the window, sound and controllers,
Vulkan (through MoltenVK, on top of Metal) for graphics and FFmpeg for the movies. No emulator.

**This is the first test on a real Mac.** Nobody has played the game on a Mac with this build yet. Expect problems, and
please report what happens (see "What to report").

## Who it is for

- An **Apple Silicon Mac** (M1 or newer). **Intel Macs are not supported.**
- **macOS 14.4 or newer.**
- About **60 GB of free disk** and **16 GB of RAM** (recommended).
- **Time:** the first build lifts and compiles the whole game. Plan for **several hours**. It can be stopped and started again.
- The **game files come from YOUR own console dump**. We do not explain how to get them and we do not provide them. The
  folder layout the build expects (`exefs/` and `romfs/`) is described in
  [BUILDING.md](BUILDING.md#what-you-dump-from-your-own-console). Nothing of the game is stored in this repository.

## The two commands

Open the Terminal (Applications > Utilities > Terminal). Type `cd ` (with a space), drag the folder of this project
from Finder into the Terminal window, and press Return. Then:

```
bash scripts/macos/install_mac.sh --dump <your dump folder>
bash play_mac.sh
```

For `<your dump folder>` you can again drag the folder from Finder into the window. `bash` in front makes the scripts run
even when the project came as a downloaded ZIP (which can lose the "executable" mark); after the install
`./play_mac.sh` works too.

The first command checks your Mac, installs the tools with Homebrew, prepares Python, and builds the game from your dump.
If the Xcode Command Line Tools or Homebrew are missing, it tells you what to do and stops; run it again after that.
`--jobs N` sets how many compilers run at most at once. The default is one per CPU core; they share your RAM minus 4 GB,
each reserving what its file is expected to need, so the few files that need many GB run with fewer beside them.

- **"Terminal would like to access files in your Documents / Desktop / Downloads folder":** click Allow (the build reads
  your dump and writes into the project folder).
- **"This Terminal runs under Rosetta":** your Terminal is set to run as an Intel program. In Finder, select
  Applications > Utilities > Terminal, File > Get Info, untick "Open using Rosetta", open Terminal again.
- **"The Homebrew found is the Intel Homebrew in /usr/local":** a Homebrew moved over from an Intel Mac. Install the Apple
  Silicon one as the script shows (it goes to /opt/homebrew, beside the other).

The second command starts the game. The first start waits at a progress screen while shaders are prepared; later starts are
faster. Saves go to `~/Library/Application Support/ssbu-recomp/userdata`. Close the window to quit.

Keyboard keys: arrows = left stick, Z X C V = A B X Y, Q E = L R, A S = ZL ZR, I J K L = d-pad, Enter / Backspace = + / −.
Controllers: any pad SDL3 knows. Remapping: `build-macos/config/controllers.ini` (written on the first start).

## What does not work yet

- Graphics use Vulkan through MoltenVK. Parts of Vulkan that the game asks for may be missing on Metal. The game may stop
  at start with a message starting with `nvn_vk:` that names the missing part. That message is useful: send it.
- Speed is unknown. It may be slow, or stutter while shaders are prepared.
- **Mods and the hook table are off** on macOS.
- The **settings menu (F1)** is built (Dear ImGui, fetched by `install_mac.sh` into `deps/imgui`): F1, a controller's
  Home / Guide button, or hold − and + together for 1 s. It compiles in CI but **has not been tried on a Mac yet**.
  Text boxes: the keyboard, or "Type in a dialog" (a macOS dialog through `osascript`).
- **Online play is off.**
- Recording movies to the album does not work (the self-test cases for it are accepted as known failures).

## If something goes wrong

- **The install stopped:** run the same command again. Finished steps are skipped and it continues where it stopped.
- **Out of memory / the Mac freezes during the build:** run again with a lower `--jobs`, for example `--jobs 2`.
- **The game crashes at start in MoltenVK:** try `MVK_CONFIG_USE_METAL_ARGUMENT_BUFFERS=0 bash play_mac.sh`.
- **Collect the logs:** run `bash scripts/macos/collect_logs_mac.sh`. It makes `~/Desktop/ssbu_mac_report_<date>.zip` with the
  build logs, the last game logs and facts about your Mac (macOS version, chip, graphics, Vulkan, Homebrew packages). It
  never includes your dump or any game file. **Send that zip** with your report.
- The newest game log is also in `build-macos/logs/`.

## What to report

Please answer these, even if the answer is "no":

1. Did the install finish? If not, **which step failed** (the line starting with `FAILED at step`)?
2. Did the game window open?
3. Did the intro movie play, **with sound**?
4. Did the title screen appear?
5. Did a fight start and run? How did the speed feel (smooth, or slow, or stuttering)?
6. Which controller did you use (keyboard, which pad)?
7. Your Mac model, chip and macOS version, and the zip from `collect_logs_mac.sh`.
