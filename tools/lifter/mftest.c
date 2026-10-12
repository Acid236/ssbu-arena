/* Offline check of Windows Media Foundation on a movie extracted from the game:
 *   mftest.exe <file> [frame-index] [out.png]
 * Lists the streams, the MF decoders available for VP8/VP9/Vorbis/Opus, asks the source reader for
 * NV12 video (and PCM audio), decodes up to the requested frame and writes it as a PNG.
 * Build: clang mftest.c -O1 -o mftest.exe -lmfplat -lmfreadwrite -lmfuuid -lole32 -lshlwapi */
#define COBJMACROS
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <initguid.h>
#include <mfapi.h>
#include <mfidl.h>
#include <mfreadwrite.h>
#include <mferror.h>
#include <shlwapi.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>

DEFINE_GUID(MFVideoFormat_VP90_local, 0x30395056, 0x0000, 0x0010, 0x80, 0x00, 0x00, 0xaa, 0x00, 0x38, 0x9b, 0x71);   /* 'VP90' */
DEFINE_GUID(MFVideoFormat_VP80_local, 0x30385056, 0x0000, 0x0010, 0x80, 0x00, 0x00, 0xaa, 0x00, 0x38, 0x9b, 0x71);   /* 'VP80' */
DEFINE_GUID(MFAudioFormat_Vorbis_local, 0x8D2FD10B, 0x5841, 0x4a6b, 0x89, 0x05, 0x58, 0x8F, 0xEC, 0x1A, 0xDE, 0xD9);
DEFINE_GUID(MFAudioFormat_Opus_local, 0x0000704F, 0x0000, 0x0010, 0x80, 0x00, 0x00, 0xaa, 0x00, 0x38, 0x9b, 0x71);

/* ------------------------------------------------------------------ tiny PNG writer (stored deflate) */
static uint32_t crc_table[256];
static void crc_init(void) { for (uint32_t n = 0; n < 256; n++) { uint32_t c = n; for (int k = 0; k < 8; k++) c = c & 1 ? 0xedb88320u ^ (c >> 1) : c >> 1; crc_table[n] = c; } }
static uint32_t crc32b(uint32_t c, const unsigned char *b, size_t n) { c = ~c; for (size_t i = 0; i < n; i++) c = crc_table[(c ^ b[i]) & 0xff] ^ (c >> 8); return ~c; }
static void put32(FILE *f, uint32_t v) { unsigned char b[4] = {v >> 24, v >> 16, v >> 8, v}; fwrite(b, 1, 4, f); }
static void chunk(FILE *f, const char *type, const unsigned char *data, size_t n) {
    put32(f, (uint32_t)n);
    unsigned char t[4]; memcpy(t, type, 4);
    fwrite(t, 1, 4, f);
    if (n) fwrite(data, 1, n, f);
    uint32_t c = crc32b(0, t, 4);
    if (n) c = crc32b(c, data, n);
    put32(f, c);
}
int write_png(const char *path, const unsigned char *rgb, int w, int h) {
    crc_init();
    FILE *f = fopen(path, "wb");
    if (!f) return 0;
    static const unsigned char sig[8] = {137, 80, 78, 71, 13, 10, 26, 10};
    fwrite(sig, 1, 8, f);
    unsigned char ihdr[13] = {w >> 24, w >> 16, w >> 8, w, h >> 24, h >> 16, h >> 8, h, 8, 2, 0, 0, 0};
    chunk(f, "IHDR", ihdr, 13);
    size_t row = (size_t)w * 3 + 1, raw = row * (size_t)h;
    unsigned char *buf = malloc(raw);
    for (int y = 0; y < h; y++) { buf[y * row] = 0; memcpy(buf + y * row + 1, rgb + (size_t)y * w * 3, (size_t)w * 3); }
    size_t blocks = (raw + 65534) / 65535, zlen = 2 + raw + blocks * 5 + 4;
    unsigned char *z = malloc(zlen), *p = z;
    *p++ = 0x78; *p++ = 0x01;
    uint32_t a = 1, b = 0;
    for (size_t i = 0; i < raw; i++) { a = (a + buf[i]) % 65521; b = (b + a) % 65521; }
    for (size_t off = 0; off < raw; off += 65535) {
        size_t n = raw - off < 65535 ? raw - off : 65535;
        *p++ = off + n == raw;
        *p++ = n & 0xff; *p++ = n >> 8; *p++ = ~n & 0xff; *p++ = (~n >> 8) & 0xff;
        memcpy(p, buf + off, n); p += n;
    }
    uint32_t adler = (b << 16) | a;
    *p++ = adler >> 24; *p++ = adler >> 16; *p++ = adler >> 8; *p++ = adler;
    chunk(f, "IDAT", z, (size_t)(p - z));
    chunk(f, "IEND", NULL, 0);
    fclose(f);
    free(buf); free(z);
    return 1;
}

/* NV12 (Y plane, then interleaved UV at half resolution) -> packed RGB, BT.709 limited range */
void nv12_to_rgb(const unsigned char *y, int ystride, const unsigned char *uv, int uvstride, int w, int h, unsigned char *rgb) {
    for (int j = 0; j < h; j++) {
        for (int i = 0; i < w; i++) {
            int Y = y[j * ystride + i] - 16, U = uv[(j / 2) * uvstride + (i & ~1)] - 128, V = uv[(j / 2) * uvstride + (i & ~1) + 1] - 128;
            float yf = 1.164f * Y;
            int r = (int)(yf + 1.793f * V), g = (int)(yf - 0.213f * U - 0.533f * V), b = (int)(yf + 2.112f * U);
            unsigned char *o = rgb + ((size_t)j * w + i) * 3;
            o[0] = r < 0 ? 0 : r > 255 ? 255 : r; o[1] = g < 0 ? 0 : g > 255 ? 255 : g; o[2] = b < 0 ? 0 : b > 255 ? 255 : b;
        }
    }
}

static const char *guid_name(const GUID *g) {
    static char buf[80];
    if (IsEqualGUID(g, &MFMediaType_Video)) return "video";
    if (IsEqualGUID(g, &MFMediaType_Audio)) return "audio";
    if (IsEqualGUID(g, &MFVideoFormat_NV12)) return "NV12";
    if (IsEqualGUID(g, &MFVideoFormat_VP90_local)) return "VP90";
    if (IsEqualGUID(g, &MFVideoFormat_VP80_local)) return "VP80";
    if (IsEqualGUID(g, &MFAudioFormat_Vorbis_local)) return "Vorbis";
    if (IsEqualGUID(g, &MFAudioFormat_Opus_local)) return "Opus";
    if (IsEqualGUID(g, &MFAudioFormat_PCM)) return "PCM";
    if (IsEqualGUID(g, &MFAudioFormat_Float)) return "Float";
    snprintf(buf, sizeof buf, "{%08lx-%04x-%04x-%02x%02x-%02x%02x%02x%02x%02x%02x}", g->Data1, g->Data2, g->Data3,
             g->Data4[0], g->Data4[1], g->Data4[2], g->Data4[3], g->Data4[4], g->Data4[5], g->Data4[6], g->Data4[7]);
    return buf;
}

static void list_decoders(const char *what, const GUID *major, const GUID *sub) {
    MFT_REGISTER_TYPE_INFO in = {*major, *sub};
    IMFActivate **acts = NULL; UINT32 n = 0;
    HRESULT hr = MFTEnumEx(IsEqualGUID(major, &MFMediaType_Video) ? MFT_CATEGORY_VIDEO_DECODER : MFT_CATEGORY_AUDIO_DECODER,
                           MFT_ENUM_FLAG_SYNCMFT | MFT_ENUM_FLAG_ASYNCMFT | MFT_ENUM_FLAG_HARDWARE | MFT_ENUM_FLAG_SORTANDFILTER, &in, NULL, &acts, &n);
    printf("decoders for %s: hr=%08lx count=%u", what, hr, n);
    for (UINT32 i = 0; i < n; i++) {
        WCHAR name[200]; UINT32 len = 0;
        if (SUCCEEDED(IMFActivate_GetString(acts[i], &MFT_FRIENDLY_NAME_Attribute, name, 200, &len))) printf("  [%ls]", name);
        IMFActivate_Release(acts[i]);
    }
    if (acts) CoTaskMemFree(acts);
    printf("\n");
}

int main(int argc, char **argv) {
    if (argc < 2) { fprintf(stderr, "usage: mftest <file> [frame] [out.png]\n"); return 2; }
    int want = argc > 2 ? atoi(argv[2]) : 60;
    const char *out = argc > 3 ? argv[3] : "frame.png";
    setvbuf(stdout, NULL, _IONBF, 0);
    CoInitializeEx(NULL, COINIT_MULTITHREADED);
    HRESULT hr = MFStartup(MF_VERSION, MFSTARTUP_FULL);
    printf("MFStartup %08lx\n", hr);
    list_decoders("VP90", &MFMediaType_Video, &MFVideoFormat_VP90_local);
    list_decoders("VP80", &MFMediaType_Video, &MFVideoFormat_VP80_local);
    list_decoders("Vorbis", &MFMediaType_Audio, &MFAudioFormat_Vorbis_local);
    list_decoders("Opus", &MFMediaType_Audio, &MFAudioFormat_Opus_local);

    WCHAR wpath[1024];
    MultiByteToWideChar(CP_ACP, 0, argv[1], -1, wpath, 1024);
    IMFAttributes *attrs = NULL;
    MFCreateAttributes(&attrs, 2);
    IMFAttributes_SetUINT32(attrs, &MF_SOURCE_READER_ENABLE_VIDEO_PROCESSING, 1);
    IMFSourceReader *rd = NULL;
    if (getenv("MFTEST_MEM")) {                       /* the way the game build feeds MF: whole file in memory, no URL */
        FILE *f = fopen(argv[1], "rb");
        fseek(f, 0, SEEK_END); long sz = ftell(f); fseek(f, 0, SEEK_SET);
        unsigned char *data = malloc((size_t)sz);
        fread(data, 1, (size_t)sz, f); fclose(f);
        IStream *st = SHCreateMemStream(data, (UINT)sz);
        free(data);
        IMFByteStream *bs = NULL;
        hr = MFCreateMFByteStreamOnStream(st, &bs);
        printf("MFCreateMFByteStreamOnStream %08lx\n", hr);
        IMFAttributes *ba = NULL;
        hr = IMFByteStream_QueryInterface(bs, &IID_IMFAttributes, (void **)&ba);
        printf("byte stream IMFAttributes %08lx\n", hr);
        if (SUCCEEDED(hr)) {
            IMFAttributes_SetString(ba, &MF_BYTESTREAM_CONTENT_TYPE, L"video/webm");
            IMFAttributes_SetString(ba, &MF_BYTESTREAM_ORIGIN_NAME, L"movie.webm");
            IMFAttributes_Release(ba);
        }
        hr = MFCreateSourceReaderFromByteStream(bs, attrs, &rd);
        printf("MFCreateSourceReaderFromByteStream %08lx\n", hr);
        if (FAILED(hr)) return 1;
    } else {
        hr = MFCreateSourceReaderFromURL(wpath, attrs, &rd);
        printf("MFCreateSourceReaderFromURL %08lx\n", hr);
        if (FAILED(hr)) return 1;
    }

    PROPVARIANT var; PropVariantInit(&var);
    if (SUCCEEDED(IMFSourceReader_GetPresentationAttribute(rd, (DWORD)MF_SOURCE_READER_MEDIASOURCE, &MF_PD_DURATION, &var)))
        printf("duration %.3f s\n", (double)var.uhVal.QuadPart / 1e7);
    PropVariantClear(&var);

    int video = -1, audio = -1;
    for (DWORD i = 0; i < 8; i++) {
        IMFMediaType *t = NULL;
        if (FAILED(IMFSourceReader_GetNativeMediaType(rd, i, 0, &t))) break;
        GUID major, sub; UINT64 fs = 0, fr = 0; UINT32 rate = 0, ch = 0;
        IMFMediaType_GetGUID(t, &MF_MT_MAJOR_TYPE, &major);
        IMFMediaType_GetGUID(t, &MF_MT_SUBTYPE, &sub);
        printf("stream %lu: %s ", i, guid_name(&major));
        printf("%s", guid_name(&sub));
        if (IsEqualGUID(&major, &MFMediaType_Video)) {
            IMFMediaType_GetUINT64(t, &MF_MT_FRAME_SIZE, &fs);
            IMFMediaType_GetUINT64(t, &MF_MT_FRAME_RATE, &fr);
            printf(" %ux%u %u/%u fps", (unsigned)(fs >> 32), (unsigned)fs, (unsigned)(fr >> 32), (unsigned)fr);
            if (video < 0) video = (int)i;
        } else {
            IMFMediaType_GetUINT32(t, &MF_MT_AUDIO_SAMPLES_PER_SECOND, &rate);
            IMFMediaType_GetUINT32(t, &MF_MT_AUDIO_NUM_CHANNELS, &ch);
            printf(" %u Hz %u ch", rate, ch);
            if (audio < 0) audio = (int)i;
        }
        printf("\n");
        IMFMediaType_Release(t);
    }
    if (video < 0) { printf("no video stream\n"); return 1; }

    IMFMediaType *vt = NULL;
    MFCreateMediaType(&vt);
    IMFMediaType_SetGUID(vt, &MF_MT_MAJOR_TYPE, &MFMediaType_Video);
    IMFMediaType_SetGUID(vt, &MF_MT_SUBTYPE, &MFVideoFormat_NV12);
    hr = IMFSourceReader_SetCurrentMediaType(rd, (DWORD)video, NULL, vt);
    printf("SetCurrentMediaType(video, NV12) %08lx\n", hr);
    IMFMediaType_Release(vt);
    if (FAILED(hr)) return 1;
    IMFMediaType *cur = NULL; UINT64 fs = 0; UINT32 stride = 0;
    IMFSourceReader_GetCurrentMediaType(rd, (DWORD)video, &cur);
    IMFMediaType_GetUINT64(cur, &MF_MT_FRAME_SIZE, &fs);
    IMFMediaType_GetUINT32(cur, &MF_MT_DEFAULT_STRIDE, &stride);
    int w = (int)(fs >> 32), h = (int)fs;
    printf("output %dx%d default stride %u\n", w, h, stride);
    IMFMediaType_Release(cur);

    if (audio >= 0) {
        IMFMediaType *at = NULL;
        MFCreateMediaType(&at);
        IMFMediaType_SetGUID(at, &MF_MT_MAJOR_TYPE, &MFMediaType_Audio);
        IMFMediaType_SetGUID(at, &MF_MT_SUBTYPE, &MFAudioFormat_PCM);
        hr = IMFSourceReader_SetCurrentMediaType(rd, (DWORD)audio, NULL, at);
        printf("SetCurrentMediaType(audio, PCM) %08lx%s\n", hr, FAILED(hr) ? " (no MF decoder for this audio codec)" : "");
        IMFMediaType_Release(at);
        if (FAILED(hr)) IMFSourceReader_SetStreamSelection(rd, (DWORD)audio, FALSE);
    }

    LARGE_INTEGER f0, t0, t1; QueryPerformanceFrequency(&f0); QueryPerformanceCounter(&t0);
    int n = 0;
    for (;;) {
        DWORD idx = 0, flags = 0; LONGLONG ts = 0; IMFSample *s = NULL;
        hr = IMFSourceReader_ReadSample(rd, (DWORD)video, 0, &idx, &flags, &ts, &s);
        if (FAILED(hr)) { printf("ReadSample failed %08lx after %d frames\n", hr, n); return 1; }
        if (flags & MF_SOURCE_READERF_ENDOFSTREAM) { printf("end of stream after %d frames\n", n); return 0; }
        if (flags & MF_SOURCE_READERF_CURRENTMEDIATYPECHANGED) printf("media type changed at frame %d\n", n);
        if (!s) continue;
        if (n == want) {
            IMFMediaBuffer *mb = NULL; BYTE *data = NULL; DWORD len = 0;
            IMFSample_ConvertToContiguousBuffer(s, &mb);
            IMFMediaBuffer_Lock(mb, &data, NULL, &len);
            IMF2DBuffer *b2 = NULL; LONG pitch = 0; BYTE *scan = NULL;
            if (SUCCEEDED(IMFMediaBuffer_QueryInterface(mb, &IID_IMF2DBuffer, (void **)&b2)) && SUCCEEDED(IMF2DBuffer_Lock2D(b2, &scan, &pitch)) && scan && pitch > 0) {
                printf("frame %d: ts %.3f s, %lu bytes, 2D pitch %ld\n", n, ts / 1e7, len, pitch);
            } else {
                if (b2) { IMF2DBuffer_Release(b2); b2 = NULL; }
                pitch = stride ? (LONG)stride : w;
                scan = data;
                printf("frame %d: ts %.3f s, %lu bytes, assumed pitch %ld\n", n, ts / 1e7, len, pitch);
            }
            unsigned char *rgb = malloc((size_t)w * h * 3);
            nv12_to_rgb(scan, pitch, scan + (size_t)pitch * h, pitch, w, h, rgb);
            write_png(out, rgb, w, h);
            printf("wrote %s\n", out);
            free(rgb);
            if (b2) { IMF2DBuffer_Unlock2D(b2); IMF2DBuffer_Release(b2); }
            IMFMediaBuffer_Unlock(mb);
            IMFMediaBuffer_Release(mb);
            IMFSample_Release(s);
            break;
        }
        IMFSample_Release(s);
        n++;
    }
    QueryPerformanceCounter(&t1);
    printf("decoded %d frames in %.3f s (%.1f ms/frame)\n", n + 1, (double)(t1.QuadPart - t0.QuadPart) / f0.QuadPart,
           1000.0 * (t1.QuadPart - t0.QuadPart) / f0.QuadPart / (n + 1));
    IMFSourceReader_Release(rd);
    MFShutdown();
    return 0;
}
