#!/bin/sh
# The FFmpeg DLLs the movie fallback loads (runtime/mf_ffmpeg.c): an LGPL build of FFmpeg with only what the game's movies
# need, no external libraries, no GPL parts. scripts/fetch_media.py downloads the result of this script (published as a
# GitHub Release asset) and checks its SHA-256; this script is how that package was made, for anyone to rebuild it.
#
#   sh build_ffmpeg_win.sh <ffmpeg-source-dir> <out-dir>
#
# Needs: an MSYS2 UCRT64 gcc (C:\msys64\ucrt64\bin on PATH), GNU make and a POSIX shell (MSYS2's), nasm on PATH.
# Source used for the published package: https://ffmpeg.org/releases/ffmpeg-8.1.3.tar.xz
#   SHA-256 7138d28c96d9d3e3af4ee3d8cad72741f8ffb40da90c1112235dea3ecd3178a3, signed by the FFmpeg release key
#   FCF9 86EA 15E6 E293 A564 4F10 B432 2F04 D676 58D8. No changes to the source.
# Paths must not contain spaces (FFmpeg's configure).
set -e
SRC=$1
OUT=$2
[ -n "$SRC" ] && [ -n "$OUT" ] || { echo "usage: $0 <ffmpeg-source-dir> <out-dir>"; exit 2; }
mkdir -p "$OUT/build"
cd "$OUT/build"
# What runtime/plat_mf.c uses: the Matroska/WebM demuxer over custom I/O; the VP9, H.264, Vorbis and Opus decoders (with
# the parsers / bitstream filter they need); libswscale (to NV12) and libswresample (to 16-bit PCM). Everything else off,
# including every autodetected system library (Media Foundation, DXVA, schannel ...): the DLLs import only Windows' own.
"$SRC/configure" \
    --prefix="$OUT/dist" --target-os=mingw32 --arch=x86_64 \
    --enable-shared --disable-static --disable-programs --disable-doc --disable-debug \
    --disable-autodetect --disable-network --disable-everything \
    --disable-avdevice --disable-avfilter \
    --enable-avformat --enable-avcodec --enable-swscale --enable-swresample \
    --enable-demuxer=matroska \
    --enable-decoder=vp9,h264,vorbis,opus \
    --enable-parser=vp9,h264,vorbis,opus \
    --enable-bsf=vp9_superframe_split \
    --enable-w32threads \
    --extra-ldflags="-static-libgcc" --extra-libs="-Wl,-Bstatic -lwinpthread -Wl,-Bdynamic"
# libgcc and winpthreads linked into the DLLs (no libgcc_s / libwinpthread-1.dll to ship). --use-temp-file: windres's popen of
# the preprocessor fails under some MSYS2 shells ("Bad file descriptor").
make -j"${JOBS:-8}" WINDRES="windres --use-temp-file"
make install WINDRES="windres --use-temp-file"
