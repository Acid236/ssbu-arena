#!/usr/bin/env python3
"""The FFmpeg package of the movie fallback, as published in the GitHub Release scripts/fetch_media.py downloads from.

    python scripts/ffmpeg/package_ffmpeg.py <out-dir of build_ffmpeg_win.sh> <ffmpeg-source-dir> <package.zip>

Puts in the zip: bin/ (the five DLLs), include/ (FFmpeg's headers, for building the runtime), COPYING.LGPLv2.1 and
README.txt (what this is, the source, the configure line). Same inputs -> byte-identical zip (fixed dates, sorted names),
so its SHA-256 can be pinned. Prints the SHA-256 of the zip and of each DLL (to copy into fetch_media.py).
"""
import hashlib
import os
import sys
import zipfile

DLLS = ('avutil-60.dll', 'swresample-6.dll', 'swscale-9.dll', 'avcodec-62.dll', 'avformat-62.dll')
README = """FFmpeg 8.1.3 for the movie fallback of ssbu-recomp (Windows x64)

What: the five FFmpeg libraries runtime/mf_ffmpeg.c loads when Windows' Media Foundation cannot play the game's movies
(no Web Media Extensions / VP9 Video Extensions, Windows N). Only the Matroska/WebM demuxer and the VP9, H.264, Vorbis and
Opus decoders are built in, with libswscale and libswresample; no external libraries. The DLLs import only Windows' own.

Licence: FFmpeg is licensed under the GNU Lesser General Public License version 2.1 or later (COPYING.LGPLv2.1). This
build has no GPL or non-free parts (configure: "License: LGPL version 2.1 or later").

Source: https://ffmpeg.org/releases/ffmpeg-8.1.3.tar.xz
  SHA-256 7138d28c96d9d3e3af4ee3d8cad72741f8ffb40da90c1112235dea3ecd3178a3
  signed by the FFmpeg release key FCF9 86EA 15E6 E293 A564 4F10 B432 2F04 D676 58D8. Not modified.
Built with scripts/ffmpeg/build_ffmpeg_win.sh of https://github.com/Denkishi/ssbu-recomp (MSYS2 UCRT64 gcc 15.2.0,
nasm 3.02). The configure line is in that script; anyone can rebuild these DLLs from the source above.
"""


def add(z, name, data):
    zi = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
    zi.compress_type = zipfile.ZIP_DEFLATED
    zi.external_attr = 0o644 << 16
    z.writestr(zi, data, compresslevel=9)


def main():
    out_dir, src, zpath = sys.argv[1:4]
    dist = os.path.join(out_dir, 'dist')
    files = {}
    for n in DLLS:
        with open(os.path.join(dist, 'bin', n), 'rb') as f:
            files['bin/' + n] = f.read()
    inc = os.path.join(dist, 'include')
    for root, _, names in os.walk(inc):
        for n in names:
            p = os.path.join(root, n)
            with open(p, 'rb') as f:
                files['include/' + os.path.relpath(p, inc).replace(os.sep, '/')] = f.read()
    with open(os.path.join(src, 'COPYING.LGPLv2.1'), 'rb') as f:
        files['COPYING.LGPLv2.1'] = f.read()
    files['README.txt'] = README.encode()
    with zipfile.ZipFile(zpath, 'w') as z:
        for name in sorted(files):
            add(z, name, files[name])
    with open(zpath, 'rb') as f:
        print('%s  %s  (%d bytes)' % (hashlib.sha256(f.read()).hexdigest(), os.path.basename(zpath), os.path.getsize(zpath)))
    for n in DLLS:
        print('%s  bin/%s' % (hashlib.sha256(files['bin/' + n]).hexdigest(), n))


if __name__ == '__main__':
    main()
