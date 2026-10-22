# Credits

## OpenSmash-Ultimate (ssbu-recomp)

SSBU Arena is built on **[OpenSmash-Ultimate, `OpenSmash-Ultimate/ssbu-recomp`](https://github.com/OpenSmash-Ultimate/ssbu-recomp)**,
licensed under the GPL-3.0. Arena started as a fork of it (`Acid236/ssbu-recomp-ldnOnline`) and became a separate
project on 2026-10-21; everything up to that point, theirs and ours, is in this repository's git history with its
original authors.

From OpenSmash-Ultimate come the static recompiler (`tools/lifter`), the extraction tools, the runtime that replaces the
console (`runtime/`), the Vulkan and OpenGL renderers, the shader translator, the installer and self-update, the
fighter SDK, the rollback snapshot ring and online rollback (`r1_*.c`, `rb_*.c`), and most of the documentation.

Its people, by commits to its main branch:

- **Denkishi**: creator and maintainer; most of the project.
- **Stephen Jayakar**
- **xtlg511**: support for game version 13.0.5, the libopus build step, a `run.py` fix.
- **v1Ta44**
- **Frank Fly**
- **Victor Navega**
- **jfb112697**: a `setup.py` check fix.

And those OpenSmash-Ultimate credits in turn:

- **SNO2207 / WindowSmash**: parts of the online network code and the lobby design are adapted with the author's
  permission (see [docs/ONLINE.md](docs/ONLINE.md)); the installer's approach was inspired by its tools (nothing copied).
- **yuzu and suyu**: the open-source system fonts shipped in `runtime/fonts_open` ([README](runtime/fonts_open/README.md)).
- **Slippi and Hero88go/melee-unlocked**: the public design of rollback netplay that guides the netcode.
- **sbergeron42/ssbu-decomp**: the matching-decompilation effort.
- yuzu and its successors, SDL, glslang, libopus, Unicorn, Capstone, the N64 static-recompilation projects and
  BelmanteGu/SuperMarioWonderRecomp, from which technique was learned.
- The Smash modding community (param labels, skyline-smash, ARCropolis) for names of script functions and constants.

## SSBU Arena

- **Acid236**: Local Wireless over the internet, the relay lobby servers (`tools/online/ldn_relay.c`,
  `tools/net/rb_lobby.c`), online rollback through the relay, the ping overlay, the competitive mode and light archive,
  the launchers.
- The SSBU Arena launcher uses the **Barlow** and **Barlow Condensed** fonts by Jeremy Tribby, under the SIL Open Font
  License 1.1 (`tools/launcher/arena/Assets/Fonts/OFL.txt`), and the artwork of [ssbuarena.com](https://ssbuarena.com/).
- The hero art is a study of hitboxes in the style of [Ultimate Frame Data](https://ultimateframedata.com/).
