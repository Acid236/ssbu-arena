# Open-source replacement system fonts

The game asks the system for 7 shared fonts. A console has them in its firmware; with a firmware dump the build
uses those (`tools/extract/fw_fonts.py`, `<dump>/sysdata/fonts`). Without one, the runtime uses the files in this
folder: open-source fonts the yuzu project put together for the same purpose, taken unmodified from the suyu
repository and saved under the file names the runtime asks for. `scripts/setup.py` copies this folder beside the
game's exe (`build/work/fonts_open`), where `nnpl.c` looks when no firmware font is found.

What changes without your firmware's fonts: Latin text uses Open Sans and Source Sans Pro instead of the console's
typefaces; Chinese, Japanese and Korean text and most symbols are missing (each missing character is drawn as an
empty box); the button icons come from yuzu's small icon font. Fights are not affected.

## Files

All seven are made by `python tools/extract/open_fonts.py <folder>` from the suyu repository at commit
`c0dd2ff554327657f0c6318f29b740ac7e329ea0` (https://github.com/suyu-emu/suyu-v0.0.4), folder
`src/core/file_sys/system_archive/data/`, where each font is a C++ array of the plain TrueType bytes. The script
checks the SHA-256 of each source file, converts the array back into the .ttf and gives the same bytes as here.

| File here | Source file (SHA-256 of the .cpp) | Font | Licence |
|---|---|---|---|
| nintendo_udsg-r_std_003.ttf | font_standard.cpp (0355fb64938bd66d96a326ab0681d551803281fe641078bf42cf84e729e5780c) | Open Sans Regular 1.10 | Apache-2.0 |
| nintendo_udsg-r_org_zh-cn_003.ttf | font_chinese_simplified.cpp (f91d1223e5c79509daf11318bf83e8ca5ed3626a0d2c6ee86d3b202f303bc0e5) | Open Sans Regular 1.10 | Apache-2.0 |
| nintendo_udsg-r_ext_zh-cn_003.ttf | font_extended_chinese_simplified.cpp (da47566f0dd8b5e28129b1dca7b2bb5f5b2af5c1841552742ed48cb27e9f4200) | Source Sans Pro Regular 2.021 | OFL-1.1 |
| nintendo_udjxh-db_zh-tw_003.ttf | font_chinese_traditional.cpp (bc6d49f2c471861e61e6a08c952088690c2bee52ef443a4fdc9a36af816b2394) | Open Sans Light 1.10 | Apache-2.0 |
| nintendo_udsg-r_ko_003.ttf | font_korean.cpp (2cb950e2de8ff3ff79c2bd88e22f7eaa70063a7c50abbd06698c81f74bf52a63) | Open Sans Regular 1.10 | Apache-2.0 |
| nintendo_ext_003.ttf | font_nintendo_extended.cpp (6fbbf5176ff4fd2024f9d150c889477f6b45ece4ac5e45d51286e32f8b13a6f2) | YuzuOSSExtension 1.000 | GPL-2.0-or-later |
| nintendo_ext2_003.ttf | font_nintendo_extended.cpp (same file as above) | YuzuOSSExtension 1.000 | GPL-2.0-or-later |

## Licences

- **Open Sans** - "Digitized data copyright (c) 2010-2011, Google Corporation." Licensed under the Apache License,
  Version 2.0 (the font's own name table says so): `LICENSE-Apache-2.0.txt`. Open Sans is a trademark of Google and
  may be registered in certain jurisdictions.
- **Source Sans Pro** - "Copyright 2010, 2012, 2014 Adobe Systems Incorporated (http://www.adobe.com/), with Reserved
  Font Name 'Source'." Licensed under the SIL Open Font License, Version 1.1: `LICENSE-OFL-1.1.txt`. Distributed
  unmodified (only the file name differs). Source is a trademark of Adobe Systems Incorporated in the United States
  and/or other countries.
- **YuzuOSSExtension** - made by the yuzu Emulator Project (copyright 2019); the suyu source file carries
  `SPDX-License-Identifier: GPL-2.0-or-later`: `LICENSE-GPL-2.0-or-later.txt`. Its source is the source file named
  above.

The licence texts: Apache-2.0 and GPL-2.0-or-later as published in suyu's `LICENSES/` folder at the same commit;
the OFL text as published by Adobe with Source Sans (`adobe-fonts/source-sans`, `LICENSE.md`), headed by the
copyright notice of the font file shipped here.
