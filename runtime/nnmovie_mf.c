/* movie:: (the SDK's video player library) on Windows Media Foundation.
 *
 * The SDK library is a port of Android's stagefright (NuMediaExtractor / MediaCodec); the game's own
 * copy lives in subsdk0, whose exported symbols (movie::NnExtractor, movie::DecoderImpl, movie::NnMediaData,
 * android::FileSource, ...) give the object layouts below.  Legend: [game] read off the game's player code
 * (0x71036e6000-0x71036f9000), [subsdk] read off subsdk0's code and vtables, [doc] public documentation.
 *
 * Objects the game allocates (16 bytes each, with f_710392dce0(16, 16)) and drives through a vtable:
 *   movie::Extractor  {vtable, impl*}   [subsdk ctor 0x22eb0]      movie::Decoder {vtable, impl*}  [subsdk 0x20db0]
 * Extractor vtable (object pointer = _ZTV + 0x10, so slot 0 is the first virtual function) [subsdk _ZTVN5movie9ExtractorE]:
 *   +00 ~Extractor   +08 deleting dtor   +10 SetDataSource(const char*)   +18 SetDataSource(const void*, int)
 *   +20 GetTrackCount(int*)   +28 GetTrackConfiguration(int, MediaData*)   +30 SelectTrack(int)   +38 UnselectTrack(int)
 *   +40 SeekTo(int64)   +48 GetTrackIndexForAvailableData(size_t*)   +50 Read(Buffer*)   +58 Advance()
 *   +60 GetSampleTime(int64*)   +68 GetSampleMetaData(MediaData*)   +70 GetBufferedRange(int64*, int64*)
 *   +78 SetDataSource(ClientStreamReader*, const char*)
 * Decoder vtable [subsdk _ZTVN5movie7DecoderE]:
 *   +00 ~Decoder   +08 deleting dtor   +10 Configure(MediaData*)   +18 RegisterClientEvents(DecoderEvents*)
 *   +20 GetOutputFormat(MediaData*)   +28 Start   +30 Stop   +38 Reset   +40 Flush
 *   +48 AcquireInputBufferIndex(int *index, int *moreAvailable)   +50 GetInputBuffer(int, Buffer*)
 *   +58 SendInputBufferForDecode(int index, int offset, int size, int64 timeUs, unsigned flags)
 *   +60 AcquireOutputBufferIndex(int *index, int64 *timeUs, unsigned *flags, int *moreAvailable)
 *   +68 GetOutputBuffer(int, Buffer*)   +70 GetOutputBufferSize(int *size, int *count)   +78 ReleaseOutputBufferIndex(int)
 *   +80 GetLastError()   +88 GetOutputBuffer(int, Buffer*, MediaData*)   +90 GetOutputBufferFormat(int, MediaData*)
 * Results: 0 = ok; the SDK wrappers return 0x1000 when there is no implementation and 0x100b for bad arguments
 * [subsdk]; the game treats 0x2000 from GetTrackIndexForAvailableData/Read as "end of data" and retries on 0x5003
 * [game 0x71036f0230, 0x71036f6ce0]; any other non-zero result from Read makes it send an end-of-stream input
 * buffer (flags 4) [game 0x71036f6dd8].  Buffer flags follow MediaCodec: 4 = end of stream [game 0x71036f0784].
 * DecoderEvents = four pointers to nn::os::EventType: +0 input buffer available, +8 output buffer available,
 * +10 output format changed, +18 error [subsdk DecoderImpl::Send*EventToClient 0x1fec0..0x1ff20; game 0x71036f0590].
 * The game's player [game 0x71036f04c0] waits on those events: input -> AcquireInputBufferIndex (repeated
 * "moreAvailable" times) and hands the index to a feed thread; the feed thread [game 0x71036f6ce0] does
 * GetTrackIndexForAvailableData -> (own track?) GetInputBuffer -> Extractor::Read(Buffer) -> GetSampleTime ->
 * SendInputBufferForDecode(index, Offset(), Size(), time, flags) -> Advance.  Output event -> AcquireOutputBufferIndex,
 * entries {index, timeUs, flags} are queued and the render path [game 0x71036f7410] calls GetOutputBufferFormat(index)
 * ("width", "height", "nv12-y-stride", "nv12-uv-offset", "nv12-y-offset"), GetOutputFormat ("nv12-colorspace"),
 * GetOutputBuffer(index, Buffer{base = its own texture memory, capacity}) and ReleaseOutputBufferIndex; it uploads
 * the Y plane (w x h at nv12-y-offset) and the UV plane (w/2 x h/2 at nv12-uv-offset).  Format event ->
 * GetOutputFormat ("width", "height").  The game's clock is in microseconds (ConvertToTimeSpan / 1000) [game 0x71036f6ff0].
 * Decoder(type, outputFormat, mode, n): type 1 = H.264 ("video/avc"), 2 = VP8, 3 = VP9, 4 = AAC ("audio/mp4a-latm"),
 * 5 = Vorbis [game 0x71036f19a0 maps the track mime to these values; seen in a run: VP9 track -> type 3]; the game asks output format 4 for video and 1 for audio,
 * mode 1 [game 0x71036f0a0c, 0x71036f0e90]; format 4 is tightly packed NV12 (size w*h + 2*((w+1)/2)*((h+1)/2),
 * Y rows then interleaved UV rows of w bytes) and 2 is ARGB [subsdk GetOutputBufferSize, ConvertDecoderOutputFormat].
 * Track configuration keys the game reads: "mime", "durationUs", "width", "height", "sample-rate", "channel-count",
 * "max-input-size" (it adds 0x5000 and passes the MediaData to Decoder::Configure) [game 0x71036f19a0, 0x71036f0a68].
 * Container types: 1 = .mp4/.m4a, 2 = .mkv, 3 = .webm [game 0x71036f1d70].  The game selects the tracks it decodes
 * with SelectTrack [game 0x71036e74cc, 0x71036f2f90] and unselects audio it will not decode [game 0x71036f0f20].
 * ClientStreamReader (the object the game passes to SetDataSource; android::FileSource uses it) [subsdk 0x1d90e0..0x1d93a0]:
 *   +10 bool Open(const char *path, void **handle)   +18 int64 ReadAt(void *handle, int64 offset, void *buf, size_t n)
 *   +20 bool Close(void *handle)   +28 int GetSize(void *handle, int64 *size)
 * movie::Buffer (0x40 bytes) [subsdk 0x23a70..0x23d30]: +0 offset(i32) +4 size(i32) +8 int32 +c uint32 +10 owns(u8)
 *   +18 capacity(u64) +20 int64 +28 base +30 nvnDev +38 nvnSync; Buffer(size_t) allocates through movie::SetAllocator's
 *   alloc(size, align, user) and the destructor frees owned memory.
 * movie::MediaData is one pointer to a key/value store [subsdk 0x23d70]; here that is a host structure.
 * movie::SetAllocator(alloc(size, align, user), free(p, user), realloc(p, size, user), user) [game 0x71036e66b4].
 * The opening movie is stream:/movie/... in data.arc: WebM, VP9 1280x720, two Vorbis 48 kHz stereo tracks, 420 s
 * (extracted copy in movie_samples\, decoded offline by mftest.exe).  Media Foundation on this PC decodes VP9
 * (VP9VideoExtensionDecoder), Vorbis (FFmpegAudioDecoder MFT) and Opus; the MKV/WebM source is mfmkvsrcsnk.dll.
 *
 * How this file maps the protocol onto IMFSourceReader: the extractor reads the whole file through the game's
 * ClientStreamReader into memory and opens it as an MF byte stream.  ReadSample(ANY_STREAM) demuxes AND decodes, so
 * the "compressed sample" handed to the game in Extractor::Read is only a token {magic, IMFSample*, time} written into
 * the decoder's input slot; Decoder::SendInputBufferForDecode moves that sample to the output queue, GetOutputBuffer
 * copies the decoded NV12 / PCM data into the game's buffer and ReleaseOutputBufferIndex frees the slot.
 *
 * Final smash movies are raw H.264 elementary streams the game reads and cuts into NAL units itself (no Extractor):
 * those decoders feed Media Foundation's H.264 decoder transform directly, see the H.264 section below.
 *
 * Environment: SSBU_MOVIE=0 keeps the failing placeholder (nnmovie.c); SSBU_MOVIE_SAVE=<file> saves what the game's
 * reader returned; SSBU_MOVIE_LOG=1 logs every decoder call; SSBU_MOVIE_TEST_RESYNC=<flag>,<n> makes the game
 * re-synchronise (pause, seek, resume) the movie at the n-th video sample, see dec_SendInputBufferForDecode;
 * SSBU_MOVIE_SAVE_H264=<file> saves the H.264 stream a final smash movie sends; SSBU_MOVIE_H264_TEST=<file> (test only)
 * decodes such a file through the H.264 path the way the game drives it and exits, see h264_selftest.
 *
 * Windows, when Media Foundation cannot play a movie (it cannot open the WebM: no or broken Web Media Extensions, Windows
 * N; or it has no decoder for a track: no VP9 Video Extensions, no Vorbis decoder; or the first read fails; or there is
 * no H.264 decoder transform): the FFmpeg fallback (mf_ffmpeg.c, plat_mf.c on FFmpeg's DLLs) takes that movie over,
 * when its DLLs are there. A movie Media Foundation plays goes exactly the way it went before. SSBU_MOVIE_FFMPEG=1
 * uses FFmpeg for every movie (tests), SSBU_MOVIE_FFMPEG=0 never. */
#define COBJMACROS
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <mfapi.h>
#include <mfidl.h>
#include <mfreadwrite.h>
#include <mferror.h>
#include <shlwapi.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "runtime.h"
#include "hostrt.h"
/* The FFmpeg fallback: built when FFmpeg's headers are on the include path (build.py: FFMPEG_ROOT/include). */
#if defined(_WIN32) && defined(__has_include)
#if __has_include(<libavcodec/avcodec.h>)
#define MOVIE_FFMPEG 1
#include "mf_ffmpeg.h"
#endif
#endif

void input_mark(const char *what);                       /* nnhid.c: anchor for scripted input */

#define A0 (c->x[0])
#define A1 (c->x[1])
#define A2 (c->x[2])
#define A3 (c->x[3])
#define A4 (c->x[4])
#define RET(v) (c->x[0] = (uint64_t)(v))

void os_signal_event(uint64_t key);                   /* os_threads.c */

#define ST_OK 0
#define ST_FAILED 0x1000
#define ST_INVALID 0x100b
#define ST_UNSUPPORTED 0x1006
#define ST_END 0x2000
#define ST_NO_INPUT 0x1011                             /* AcquireInputBufferIndex: nothing offered [subsdk 0x1fac8] */
#define ST_NO_OUTPUT 0x100e                            /* AcquireOutputBufferIndex: nothing decoded [subsdk 0x1e8d0] */
#define FLAG_EOS 4
#define MAX_TRACKS 8
#define SLOT_BYTES 64
#define GAME_FREE GA(0x710392e590ULL)                     /* the game's free, as in libcxx.c */
#define TOKEN_MAGIC 0x4d4f564945544f4bULL             /* "MOVIETOK" */

/* ---------------------------------------------------------------- small helpers */
static int g_log;                                     /* SSBU_MOVIE_LOG */
static int g_test_resync_flag, g_test_resync_at;      /* SSBU_MOVIE_TEST_RESYNC */
static int g_test_resync_flag2, g_test_resync_ms;
static DWORD WINAPI test_resync_later(void *req) {
    Sleep((DWORD)g_test_resync_ms);
    InterlockedOr8((char *)req, (char)g_test_resync_flag2);
    printf("movie: TEST: resync request %d raised %d ms later\n", g_test_resync_flag2, g_test_resync_ms);
    return 0;
}
static uint64_t g_alloc_fn, g_free_fn, g_alloc_user;  /* movie::SetAllocator */
static volatile LONG g_mf_started;
static __declspec(thread) int t_com_init;

/* Whether Media Foundation is on this PC at all. The exe delay-loads MFPlat.dll / MFReadWrite.dll (build.py), so it also
 * starts on Windows N without the Media Feature Pack; nothing of Media Foundation may be called there (nnalbum.c asks too). */
int movie_mf_present(void) {
#ifdef _WIN32
    static volatile LONG known = -1;
    if (known < 0) {
        int ok = LoadLibraryW(L"mfplat.dll") != NULL && LoadLibraryW(L"mfreadwrite.dll") != NULL;
        if (getenv("SSBU_MOVIE_TEST_NO_MF")) ok = 0;      /* TEST ONLY: run as on Windows N */
        if (!ok) printf("movie: Media Foundation is not on this PC (Windows N without the Media Feature Pack?)\n");
        InterlockedExchange(&known, ok);
    }
    return known > 0;
#else
    return 1;
#endif
}

static void vorbis_store_register(void);
static void com_init(void) {
    if (!t_com_init) { CoInitializeEx(NULL, COINIT_MULTITHREADED); t_com_init = 1; }
    if (!g_mf_started && movie_mf_present() && InterlockedCompareExchange(&g_mf_started, 1, 0) == 0) {
        HRESULT hr = MFStartup(MF_VERSION, MFSTARTUP_FULL);
        printf("movie: MFStartup %08lx\n", hr);
        vorbis_store_register();
    }
}

/* The FFmpeg fallback (Windows): SSBU_MOVIE_FFMPEG=1 always, =0 never, otherwise when Media Foundation fails. */
#ifdef MOVIE_FFMPEG
static int ffmf_mode(void) {
    static int mode = -2;
    if (mode == -2) { const char *v = getenv("SSBU_MOVIE_FFMPEG"); mode = v && *v ? (atoi(v) ? 1 : 0) : -1; }
    return mode;
}
static int ffmf_forced(void) { return ffmf_mode() == 1 && ffmf_available(); }
static int ffmf_allowed(void) { return ffmf_mode() != 0 && ffmf_available(); }
/* TEST ONLY, SSBU_MOVIE_TEST_MF: Media Foundation made to fail the way PCs without working codecs do, so the fallback's
 * ways in can be run here: 1 = it cannot open the WebM (c00d36c4), 2 = no decoder for any track, 3 = the first read fails. */
static int ffmf_test(void) {
    static int t = -1;
    if (t < 0) { const char *v = getenv("SSBU_MOVIE_TEST_MF"); t = v ? atoi(v) : 0; if (t) printf("movie: TEST: SSBU_MOVIE_TEST_MF=%d\n", t); }
    return t;
}
#endif
/* A new Media Foundation object of the same side as `like` (a reader or a transform): FFmpeg's or Media Foundation's. */
static HRESULT new_media_type(const void *like, IMFMediaType **t) {
#ifdef MOVIE_FFMPEG
    if (like && FFMF_IS(like)) return ffmf_MFCreateMediaType(t);
#endif
    (void)like;
    return MFCreateMediaType(t);
}
static HRESULT new_sample(const void *like, IMFSample **smp) {
#ifdef MOVIE_FFMPEG
    if (like && FFMF_IS(like)) return ffmf_MFCreateSample(smp);
#endif
    (void)like;
    return MFCreateSample(smp);
}
static HRESULT new_buffer(const void *like, DWORD size, IMFMediaBuffer **b) {
#ifdef MOVIE_FFMPEG
    if (like && FFMF_IS(like)) return ffmf_MFCreateMemoryBuffer(size, b);
#endif
    (void)like;
    return MFCreateMemoryBuffer(size, b);
}

/* Call a guest function with up to five arguments; the caller's registers are preserved. */
static uint64_t gcall(Ctx *c, uint64_t fn, uint64_t a0, uint64_t a1, uint64_t a2, uint64_t a3, uint64_t a4) {
    uint64_t save[9], lr = c->x[30], f = c->fn;
    memcpy(save, c->x, sizeof save);
    c->x[0] = a0; c->x[1] = a1; c->x[2] = a2; c->x[3] = a3; c->x[4] = a4;
    call_guest(c, fn);
    uint64_t r = c->x[0];
    memcpy(c->x, save, sizeof save);
    c->x[30] = lr; c->fn = f;
    return r;
}

static void *galloc(Ctx *c, size_t size, size_t align, int *owns) {
    if (g_alloc_fn) {
        void *p = (void *)(uintptr_t)gcall(c, g_alloc_fn, size, align, g_alloc_user, 0, 0);
        if (p) { *owns = 1; return p; }
    }
    *owns = 2;
    return _aligned_malloc(size ? size : 16, align < 16 ? 16 : align);
}
static void gfree(Ctx *c, void *p, int owns) {
    if (!p) return;
    if (owns == 1 && g_free_fn) gcall(c, g_free_fn, (uint64_t)(uintptr_t)p, g_alloc_user, 0, 0, 0);
    else if (owns == 2) _aligned_free(p);
}

/* ---------------------------------------------------------------- movie::MediaData */
enum { MD_NONE, MD_I32, MD_I64, MD_F32, MD_F64, MD_STR, MD_PTR, MD_SIZE, MD_RECT, MD_BUF };
typedef struct { char key[40]; int type; int32_t i32; int64_t i64; float f32; double f64; char *str; uint64_t ptr; int rect[4]; } MDEntry;
typedef struct { int n; MDEntry e[40]; } MD;

static MD *md_of(uint64_t guest) { return guest ? (MD *)(uintptr_t)rd64(guest) : NULL; }
static MDEntry *md_find(MD *m, const char *key) {
    if (!m) return NULL;
    for (int i = 0; i < m->n; i++) if (strcmp(m->e[i].key, key) == 0) return &m->e[i];
    return NULL;
}
static MDEntry *md_put(MD *m, const char *key, int type) {
    MDEntry *e = md_find(m, key);
    if (!e) {
        if (m->n >= (int)(sizeof m->e / sizeof m->e[0])) return NULL;
        e = &m->e[m->n++];
        memset(e, 0, sizeof *e);
        strncpy(e->key, key, sizeof e->key - 1);
    } else if (e->str) { free(e->str); e->str = NULL; }
    e->type = type;
    return e;
}
static void md_set_i32(MD *m, const char *k, int32_t v) { MDEntry *e = md_put(m, k, MD_I32); if (e) e->i32 = v; }
static void md_set_i64(MD *m, const char *k, int64_t v) { MDEntry *e = md_put(m, k, MD_I64); if (e) e->i64 = v; }
static void md_set_f32(MD *m, const char *k, float v) { MDEntry *e = md_put(m, k, MD_F32); if (e) e->f32 = v; }
static void md_set_str(MD *m, const char *k, const char *v) { MDEntry *e = md_put(m, k, MD_STR); if (e) e->str = _strdup(v ? v : ""); }
static void md_set_ptr(MD *m, const char *k, uint64_t v) { MDEntry *e = md_put(m, k, MD_PTR); if (e) e->ptr = v; }
/* An MD_BUF entry owns a malloc'd block of i64 bytes, kept in str: md_put and md_clear free it like a string, and the
 * copy constructor and operator= copy it (md_dup_data). Used for the H.264 parameter sets. */
static void md_set_buf_owned(MD *m, const char *k, void *p, size_t n) { MDEntry *e = md_put(m, k, MD_BUF); if (e) { e->str = (char *)p; e->i64 = (int64_t)n; } else free(p); }
static int md_get_buf(MD *m, const char *k, const unsigned char **p, size_t *n) {
    MDEntry *e = md_find(m, k);
    if (!e || e->type != MD_BUF || !e->str || e->i64 <= 0) return 0;
    *p = (const unsigned char *)e->str; *n = (size_t)e->i64;
    return 1;
}
static char *md_dup_data(const MDEntry *e) {          /* the copy of an entry's own data: a string, or an MD_BUF block */
    if (!e->str) return NULL;
    if (e->type != MD_BUF) return _strdup(e->str);
    char *p = e->i64 > 0 ? malloc((size_t)e->i64) : NULL;
    if (p) memcpy(p, e->str, (size_t)e->i64);
    return p;
}
static void md_clear(MD *m) { if (!m) return; for (int i = 0; i < m->n; i++) free(m->e[i].str); m->n = 0; }
static int md_get_i32(MD *m, const char *k, int32_t *out) {
    MDEntry *e = md_find(m, k);
    if (!e) return 0;
    if (e->type == MD_I32) *out = e->i32; else if (e->type == MD_I64) *out = (int32_t)e->i64; else if (e->type == MD_SIZE) *out = (int32_t)e->i64; else return 0;
    return 1;
}
static int md_get_i64(MD *m, const char *k, int64_t *out) {
    MDEntry *e = md_find(m, k);
    if (!e) return 0;
    if (e->type == MD_I64 || e->type == MD_SIZE) *out = e->i64; else if (e->type == MD_I32) *out = e->i32; else return 0;
    return 1;
}
static int md_get_str(MD *m, const char *k, const char **out) { MDEntry *e = md_find(m, k); if (!e || e->type != MD_STR) return 0; *out = e->str; return 1; }
static int md_get_ptr(MD *m, const char *k, uint64_t *out) { MDEntry *e = md_find(m, k); if (!e || e->type != MD_PTR) return 0; *out = e->ptr; return 1; }

static void mdata_ctor(Ctx *c) { MD *m = calloc(1, sizeof *m); wr64(A0, (uint64_t)(uintptr_t)m); }
static void mdata_copy_ctor(Ctx *c) {                 /* MediaData(const MediaData &) */
    MD *m = calloc(1, sizeof *m), *src = md_of(A1);
    if (src) { *m = *src; for (int i = 0; i < m->n; i++) if (m->e[i].str) m->e[i].str = md_dup_data(&m->e[i]); }
    wr64(A0, (uint64_t)(uintptr_t)m);
}
static void mdata_dtor(Ctx *c) { MD *m = md_of(A0); if (m) { md_clear(m); free(m); wr64(A0, 0); } }
static void mdata_Clear(Ctx *c) { md_clear(md_of(A0)); }
static void mdata_SetInt32(Ctx *c) { MD *m = md_of(A0); if (m) md_set_i32(m, (const char *)(uintptr_t)A1, (int32_t)A2); }
static void mdata_SetInt64(Ctx *c) { MD *m = md_of(A0); if (m) md_set_i64(m, (const char *)(uintptr_t)A1, (int64_t)A2); }
static void mdata_SetString(Ctx *c) { MD *m = md_of(A0); if (m) md_set_str(m, (const char *)(uintptr_t)A1, (const char *)(uintptr_t)A2); }
static void mdata_SetFloat(Ctx *c) { MD *m = md_of(A0); if (m) md_set_f32(m, (const char *)(uintptr_t)A1, c->v[0].f[0]); }
static void mdata_SetPointer(Ctx *c) { MD *m = md_of(A0); if (m) md_set_ptr(m, (const char *)(uintptr_t)A1, A2); }
static void mdata_FindInt32(Ctx *c) { int32_t v = 0; int ok = md_get_i32(md_of(A0), (const char *)(uintptr_t)A1, &v); if (ok && A2) wr32(A2, (uint32_t)v); RET(ok); }
static void mdata_FindInt64(Ctx *c) { int64_t v = 0; int ok = md_get_i64(md_of(A0), (const char *)(uintptr_t)A1, &v); if (ok && A2) wr64(A2, (uint64_t)v); RET(ok); }
static void mdata_FindString(Ctx *c) { const char *s = NULL; int ok = md_get_str(md_of(A0), (const char *)(uintptr_t)A1, &s); if (ok && A2) wr64(A2, (uint64_t)(uintptr_t)s); RET(ok); }
static void mdata_FindPointer(Ctx *c) { uint64_t v = 0; int ok = md_get_ptr(md_of(A0), (const char *)(uintptr_t)A1, &v); if (ok && A2) wr64(A2, v); RET(ok); }
static void mdata_Contains(Ctx *c) { RET(md_find(md_of(A0), (const char *)(uintptr_t)A1) != NULL); }
static void mdata_CountEntries(Ctx *c) { MD *m = md_of(A0); RET(m ? m->n : 0); }
static void mdata_assign(Ctx *c) {                    /* operator= */
    MD *m = md_of(A0), *src = md_of(A1);
    if (m && src && m != src) { md_clear(m); *m = *src; for (int i = 0; i < m->n; i++) if (m->e[i].str) m->e[i].str = md_dup_data(&m->e[i]); }
    RET(A0);
}

/* ---------------------------------------------------------------- movie::Buffer */
#define B_OFFSET 0x00
#define B_SIZE 0x04
#define B_I32 0x08
#define B_U32 0x0c
#define B_OWNS 0x10
#define B_CAP 0x18
#define B_I64 0x20
#define B_BASE 0x28
#define B_DEV 0x30
#define B_SYNC 0x38

static void buf_zero(uint64_t b) { memset((void *)(uintptr_t)b, 0, 0x40); }
static void buf_ctor(Ctx *c) { buf_zero(A0); }
static void buf_ctor_size(Ctx *c) {                   /* Buffer(size_t capacity): owns its memory */
    uint64_t b = A0, cap = A1;
    int owns = 0;
    void *p = galloc(c, (size_t)cap, 16, &owns);
    buf_zero(b);
    wr64(b + B_CAP, cap);
    wr64(b + B_BASE, (uint64_t)(uintptr_t)p);
    wr8(b + B_OWNS, (uint8_t)(p ? owns : 0));
}
static void buf_ctor_data(Ctx *c) {                   /* Buffer(void *data, size_t capacity): borrowed */
    uint64_t b = A0;
    buf_zero(b);
    wr64(b + B_BASE, A1);
    wr64(b + B_CAP, A2);
}
static void buf_copy_from(Ctx *c, uint64_t b, uint64_t src) {
    uint8_t owns = rd8(src + B_OWNS);
    uint64_t cap = rd64(src + B_CAP), base = rd64(src + B_BASE);
    wr32(b + B_OFFSET, rd32(src + B_OFFSET)); wr32(b + B_SIZE, rd32(src + B_SIZE));
    wr32(b + B_I32, rd32(src + B_I32)); wr32(b + B_U32, rd32(src + B_U32));
    wr64(b + B_I64, rd64(src + B_I64)); wr64(b + B_DEV, rd64(src + B_DEV)); wr64(b + B_SYNC, rd64(src + B_SYNC));
    wr64(b + B_CAP, cap);
    if (owns && base) {                               /* an owning buffer is deep-copied */
        int o = 0;
        void *p = galloc(c, (size_t)cap, 16, &o);
        if (p) memcpy(p, (void *)(uintptr_t)base, (size_t)cap);
        wr64(b + B_BASE, (uint64_t)(uintptr_t)p);
        wr8(b + B_OWNS, (uint8_t)(p ? o : 0));
    } else {
        wr64(b + B_BASE, base);
        wr8(b + B_OWNS, 0);
    }
}
static void buf_release(Ctx *c, uint64_t b) {
    uint8_t owns = rd8(b + B_OWNS);
    if (owns) gfree(c, (void *)(uintptr_t)rd64(b + B_BASE), owns);
    wr64(b + B_BASE, 0);
    wr8(b + B_OWNS, 0);
}
static void buf_copy_ctor(Ctx *c) { buf_zero(A0); buf_copy_from(c, A0, A1); }
static void buf_assign(Ctx *c) { if (A0 != A1) { buf_release(c, A0); buf_copy_from(c, A0, A1); } RET(A0); }
/* ~Buffer frees owned memory only; a borrowed buffer's fields are left as they are (the game's audio output object clears
 * its pool of borrowed Buffers in its reset [0x71036f5ad0] without the object's mutex: a reader racing it should see the old
 * pointer, not 0). The address-0 copy of runs osk1 / det_ga1 had another cause: see aout_flush_hook. */
static void buf_dtor(Ctx *c) { if (rd8(A0 + B_OWNS)) buf_release(c, A0); }
static void buf_SetDataAndCapacity(Ctx *c) { buf_release(c, A0); wr64(A0 + B_BASE, A1); wr64(A0 + B_CAP, A2); }
static void buf_SetCapacity(Ctx *c) { wr64(A0 + B_CAP, A1); }
static void buf_SetRange(Ctx *c) { wr32(A0 + B_OFFSET, (uint32_t)A1); wr32(A0 + B_SIZE, (uint32_t)A2); }
static void buf_Base(Ctx *c) { RET(rd64(A0 + B_BASE)); }
static void buf_Data(Ctx *c) { RET(rd64(A0 + B_BASE) + (int32_t)rd32(A0 + B_OFFSET)); }
static void buf_Size(Ctx *c) { RET(rd32(A0 + B_SIZE)); }
static void buf_Offset(Ctx *c) { RET(rd32(A0 + B_OFFSET)); }
static void buf_Capacity(Ctx *c) { RET(rd64(A0 + B_CAP)); }
static void buf_SetInt32Data(Ctx *c) { wr32(A0 + B_I32, (uint32_t)A1); }
static void buf_SetInt64Data(Ctx *c) { wr64(A0 + B_I64, A1); }
static void buf_SetUint32Data(Ctx *c) { wr32(A0 + B_U32, (uint32_t)A1); }
static void buf_GetInt32Data(Ctx *c) { RET(rd32(A0 + B_I32)); }
static void buf_GetInt64Data(Ctx *c) { RET(rd64(A0 + B_I64)); }
static void buf_GetUint32Data(Ctx *c) { RET(rd32(A0 + B_U32)); }
static void buf_SetNvnDev(Ctx *c) { wr64(A0 + B_DEV, A1); }
static void buf_GetNvnDev(Ctx *c) { RET(rd64(A0 + B_DEV)); }
static void buf_SetNvnSync(Ctx *c) { wr64(A0 + B_SYNC, A1); }
static void buf_GetNvnSync(Ctx *c) { RET(rd64(A0 + B_SYNC)); }
static void buf_Swap(Ctx *c) { unsigned char t[0x40]; memcpy(t, (void *)(uintptr_t)A0, 0x40); memcpy((void *)(uintptr_t)A0, (void *)(uintptr_t)A1, 0x40); memcpy((void *)(uintptr_t)A1, t, 0x40); }

/* ---------------------------------------------------------------- Media Foundation plumbing */
typedef struct {
    int kind;                                         /* 0 video, 1 audio, 2 other */
    char mime[48];
    int w, h, rate, ch, selected, eos;
    double fps;
    uint32_t fourcc;
    int failed;                                       /* close4: the source reader's decoder reported an error for this track */
} Track;

typedef struct Ext {
    CRITICAL_SECTION cs;
    IMFSourceReader *rd;
    IMFByteStream *bs;
    int ntracks;
    Track tr[MAX_TRACKS];
    int64_t duration_us;
    int have_pending, pend_track, pend_consumed, eos;
    IMFSample *pending;
    int64_t pend_us;
    struct { int have; IMFSample *s; int64_t us; } ahead[MAX_TRACKS];    /* next decoded sample of each selected track */
    char path[260];
    unsigned long long samples_read;
    unsigned long long seek_base;                     /* samples_read at the last SeekTo (SSBU_SKIP_MOVIES counts from there) */
    int skip_eos;                                     /* (hs13) SSBU_SKIP_MOVIES ended this stream early */
    volatile uint64_t gen;                           /* bumped by SeekTo: samples read before it are refused by the decoders */
} Ext;

/* Decoder buffer model, as in the real library [subsdk DecoderImpl 0x1e440 Flush, 0x1fa30 AcquireInputBufferIndex,
 * 0x1e710 AcquireOutputBufferIndex, 0x1ff40/0x20050 Add...List]: TWO independent pools.
 *   input buffers  0..nin-1 : the codec offers an index when it can take data ("input list", one event per index);
 *                             AcquireInputBufferIndex pops the first one (*more = how many are left, 0x1011 when the
 *                             list is empty); SendInputBufferForDecode gives it back to the codec, which offers it
 *                             again as soon as the data is consumed - it does NOT wait for the decoded frame to be shown.
 *   output buffers 0..nout-1: a decoded frame sits in one from "output list" (AcquireOutputBufferIndex pops, 0x100e
 *                             when empty) until ReleaseOutputBufferIndex. When every output buffer is in use the codec
 *                             stops consuming input (back-pressure): the sent input stays "in decode".
 * Flush [subsdk 0x1e440] = MediaCodec::flush + both lists emptied, no event: every index the client still holds is
 * void, and nothing is offered until Start (MediaCodec::start after a flush offers all input buffers again).
 * The game's Seek [game 0x71036e7620] does exactly Flush(video), Flush(audio), empties its own index lists,
 * Extractor::SeekTo, sleeps 16 ms, empties the lists again, Start(video), Start(audio). */
#define MAX_IN 16
#define MAX_OUT 64
enum { IN_CODEC = 0, IN_OFFERED, IN_CLIENT, IN_DECODING };
enum { OUT_FREE = 0, OUT_READY, OUT_CLIENT };
typedef struct { int state; IMFSample *s; int64_t ts; uint32_t flags; } OutBuf;

typedef struct {
    CRITICAL_SECTION cs;
    int type, fmt, mode, is_video;
    Ext *ext;
    int track;
    uint64_t events;                                  /* guest DecoderEvents* */
    int started, flushed, fmt_signalled;
    int nin, nout;
    unsigned char in_state[MAX_IN];
    int in_list[MAX_IN], in_n;                        /* offered input indices, oldest first */
    struct { IMFSample *s; int64_t ts; uint32_t flags; } in_data[MAX_IN];   /* what an IN_DECODING buffer holds */
    int dec_list[MAX_IN], dec_n;                      /* inputs waiting for a free output buffer, oldest first */
    OutBuf out[MAX_OUT];
    int out_list[MAX_OUT], out_n;                     /* decoded frames ready for the client, oldest first */
    unsigned char *mem;                               /* nin * slot bytes: the "input buffers" */
    int w, h, rate, ch;
    unsigned long long in_count, out_count, copied, dropped, flushes;
    int warned_small, warned_token;
    uint32_t last_error;                              /* DecoderImpl +0xd8 [subsdk 0x1fc80] */
    uint64_t guest;                                   /* the game's 16-byte Decoder object (see dec_of) */
    volatile int dead;                                /* set by the destructor under the lock: every method then answers ST_INVALID */
    size_t slot;                                      /* bytes per input buffer: SLOT_BYTES for tokens, more for H.264 data */
    /* H.264 elementary stream: the game reads the compressed stream itself (no Extractor) and writes NAL units into the
     * input buffers [final smash movies, game 0x71036e568c / 0x71036f04c0]; Media Foundation's H.264 decoder transform
     * decodes them here. Decoded frames wait in pend[] until an output buffer is free. */
    int h264, csd_sent, plane_h, mft_provides, warned_h264;
    IMFTransform *mft;
    DWORD mft_out_size;
    unsigned char *csd; size_t csd_len;               /* start code + SPS + start code + PPS, sent before the first unit (owned) */
    struct { IMFSample *s; int64_t ts; uint32_t flags; } pend[MAX_OUT];
    int pend_n;
    int64_t last_ts;
    int eos_in;                                       /* end of stream received: no input buffer is offered again until a flush */
    int parked[MAX_IN], parked_n;                     /* input buffers held back while decoded frames wait (back-pressure) */
    FILE *save;                                       /* SSBU_MOVIE_SAVE_H264=<file>: what the game sent, for offline tests */
    DWORD feeder_tid;                                 /* (V 22/10) the game's feed thread of this track (the one that calls GetInputBuffer), see feeder_found_empty */
    ULONGLONG client_since[MAX_IN];                   /* tick at which the game acquired each input index */
    unsigned long long rescued;
} Dec;

/* Live decoders. The game can still call a Decoder through a pointer it holds after another thread destroyed it
 * (seen 2026-10-15: the final smash movie's worker thread [game 0x71036f05bc] after MOVIE_STOP deleted the decoder,
 * a host access violation in the forced final smash runs); the 16-byte object is then freed game
 * memory, so the implementation pointer read from it is not trusted: it must be a decoder of this list made for that
 * very object. Destroyed decoders are unlisted and marked dead under their lock, and their structure (with its
 * critical section) is kept, a few KB per decoder, so a call already running on another thread never touches freed
 * host memory: it finds d->dead after taking the lock (dec_enter) and answers ST_INVALID. */
#define MAX_LIVE_DEC 64
static SRWLOCK g_dec_live_lock = SRWLOCK_INIT;
static void *g_dec_live[MAX_LIVE_DEC];
/* The input buffers of the last destroyed H.264 decoder, freed when the next one is destroyed. The game writes the NAL
 * units into a buffer itself (GetInputBuffer, copy, SendInputBufferForDecode), and its movie threads are not stopped
 * before the decoder is deleted (see above), so one may still be copying into it; a block of 16 MB or more goes back to
 * the system at once and that copy would fault. The WebM token slots (8 x 64 bytes) are freed as before. */
static void *volatile g_h264_mem_grace;

typedef struct { uint64_t magic; IMFSample *s; int64_t ts; uint64_t gen; } Token;   /* gen = Ext::gen when it was read */

static const GUID GUID_Vorbis = {0x8D2FD10B, 0x5841, 0x4a6b, {0x89, 0x05, 0x58, 0x8F, 0xEC, 0x1A, 0xDE, 0xD9}};

/* The Vorbis decoder is not part of Windows: it comes with the Store package Web Media Extensions (FFmpegAudioDecoder).
 * Some versions of that package (1.2.42 on Windows 10, reported 2026-10-14) register it to run out of process; Media
 * Foundation then counts it as an UNTRUSTED Store decoder, which MFTEnumEx lists only with
 * MFT_ENUM_FLAG_UNTRUSTED_STOREMFT and the source reader never asks for. The reader then has no path from Vorbis to
 * PCM (c00d5212), the movie's audio track stays unselected and the opening movie stays black. So, at
 * MFStartup and only when no trusted Vorbis decoder exists, a class factory that activates the Store decoder is
 * registered for this process alone (MFTRegisterLocal; nothing changes on the system, nothing is installed). On a PC
 * whose reader already finds a Vorbis decoder (Web Media Extensions 2.x) nothing is registered and nothing changes.
 * Reported measurement with a VP9 + 2 x Vorbis WebM: both audio tracks decode, PCM equal to ffmpeg's within 0.1 per
 * 16-bit sample. IMFSourceReaderEx::AddTransformForStream with this decoder was tried there and crashed in MFPlat. */
static HRESULT STDMETHODCALLTYPE vf_QueryInterface(IClassFactory *This, REFIID riid, void **ppv) {
    if (IsEqualIID(riid, &IID_IUnknown) || IsEqualIID(riid, &IID_IClassFactory)) { *ppv = This; return S_OK; }
    *ppv = NULL; return E_NOINTERFACE;
}
static ULONG STDMETHODCALLTYPE vf_AddRef(IClassFactory *This) { (void)This; return 2; }       /* a static object */
static ULONG STDMETHODCALLTYPE vf_Release(IClassFactory *This) { (void)This; return 1; }
static HRESULT STDMETHODCALLTYPE vf_CreateInstance(IClassFactory *This, IUnknown *outer, REFIID riid, void **ppv) {
    (void)This;
    if (!ppv) return E_POINTER;
    *ppv = NULL;
    if (outer) return CLASS_E_NOAGGREGATION;
    MFT_REGISTER_TYPE_INFO in = {MFMediaType_Audio, GUID_Vorbis};
    IMFActivate **acts = NULL; UINT32 n = 0;            /* no MFT_ENUM_FLAG_LOCALMFT: this factory never lists itself */
    HRESULT hr = MFTEnumEx(MFT_CATEGORY_AUDIO_DECODER, MFT_ENUM_FLAG_SYNCMFT | MFT_ENUM_FLAG_ASYNCMFT | MFT_ENUM_FLAG_UNTRUSTED_STOREMFT | MFT_ENUM_FLAG_SORTANDFILTER, &in, NULL, &acts, &n);
    if (SUCCEEDED(hr)) hr = n ? IMFActivate_ActivateObject(acts[0], riid, ppv) : MF_E_TOPO_CODEC_NOT_FOUND;
    for (UINT32 i = 0; i < n; i++) IMFActivate_Release(acts[i]);
    CoTaskMemFree(acts);
    return hr;
}
static HRESULT STDMETHODCALLTYPE vf_LockServer(IClassFactory *This, BOOL lock) { (void)This; (void)lock; return S_OK; }
static IClassFactoryVtbl vf_vtbl = {vf_QueryInterface, vf_AddRef, vf_Release, vf_CreateInstance, vf_LockServer};
static IClassFactory vf_factory = {&vf_vtbl};
static UINT32 vorbis_count(UINT32 flags) {            /* Vorbis -> audio decoders MFTEnumEx lists with these extra flags */
    MFT_REGISTER_TYPE_INFO in = {MFMediaType_Audio, GUID_Vorbis};
    IMFActivate **acts = NULL; UINT32 n = 0;
    if (FAILED(MFTEnumEx(MFT_CATEGORY_AUDIO_DECODER, MFT_ENUM_FLAG_SYNCMFT | MFT_ENUM_FLAG_ASYNCMFT | MFT_ENUM_FLAG_SORTANDFILTER | flags, &in, NULL, &acts, &n))) n = 0;
    for (UINT32 i = 0; i < n; i++) IMFActivate_Release(acts[i]);
    CoTaskMemFree(acts);
    return n;
}
static void vorbis_hint(void) {                       /* once per process: what the user can do */
    static volatile LONG said;
    if (InterlockedExchange(&said, 1) == 0)
        printf("movie: no Vorbis decoder on this PC: install Web Media Extensions 2.x from the Microsoft Store, or set SSBU_SKIP_MOVIES=1\n");
}
static void vorbis_store_register(void) {             /* com_init, once, right after MFStartup */
    if (vorbis_count(MFT_ENUM_FLAG_LOCALMFT)) return;                 /* a trusted decoder: the reader finds it by itself */
    if (!vorbis_count(MFT_ENUM_FLAG_UNTRUSTED_STOREMFT)) { vorbis_hint(); return; }
    MFT_REGISTER_TYPE_INFO in = {MFMediaType_Audio, GUID_Vorbis}, out = {MFMediaType_Audio, MFAudioFormat_Float};
    HRESULT hr = MFTRegisterLocal(&vf_factory, &MFT_CATEGORY_AUDIO_DECODER, L"FFmpegAudioDecoder (Store, process-local)", 0, 1, &in, 1, &out);
    printf("movie: the Vorbis decoder is an untrusted Store decoder on this PC; registered for this process: %08lx\n", hr);
}

static int is_mf_fourcc_guid(const GUID *g) {         /* {xxxxxxxx-0000-0010-8000-00AA00389B71} */
    static const unsigned char tail[8] = {0x80, 0x00, 0x00, 0xAA, 0x00, 0x38, 0x9B, 0x71};
    return g->Data2 == 0 && g->Data3 == 0x10 && memcmp(g->Data4, tail, 8) == 0;
}
#define FCC(a, b, c, d) ((uint32_t)(a) | ((uint32_t)(b) << 8) | ((uint32_t)(c) << 16) | ((uint32_t)(d) << 24))

static void signal_event(Dec *d, int which) {
    if (!d->events) return;
    uint64_t ev = rd64(d->events + (uint64_t)which * 8);
    if (ev) os_signal_event(ev);
}

static void ext_lock(Ext *e) { EnterCriticalSection(&e->cs); }
static void ext_unlock(Ext *e) { LeaveCriticalSection(&e->cs); }

static Ext *ext_of(uint64_t guest) { return guest ? (Ext *)(uintptr_t)rd64(guest + 8) : NULL; }
static Dec *dec_of(uint64_t guest) {                  /* only a listed decoder made for this very object (g_dec_live) */
    if (!guest) return NULL;
    void *p = (void *)(uintptr_t)rd64(guest + 8);
    Dec *d = NULL;
    AcquireSRWLockShared(&g_dec_live_lock);
    for (int i = 0; i < MAX_LIVE_DEC && p; i++) if (g_dec_live[i] == p) { d = (Dec *)p; break; }
    ReleaseSRWLockShared(&g_dec_live_lock);
    return d && d->guest == guest ? d : NULL;
}
static int dec_listed(Dec *d, int on) {               /* lists / unlists a decoder; 0 when listing found no free slot */
    int done = 0;
    AcquireSRWLockExclusive(&g_dec_live_lock);
    if (on)                                           /* a decoder built over an object that was never destroyed can no longer be reached: its slot is freed */
        for (int i = 0; i < MAX_LIVE_DEC; i++) if (g_dec_live[i] && ((Dec *)g_dec_live[i])->guest == d->guest) g_dec_live[i] = NULL;
    for (int i = 0; i < MAX_LIVE_DEC; i++) if (on ? !g_dec_live[i] : g_dec_live[i] == d) { g_dec_live[i] = on ? d : NULL; done = 1; break; }
    ReleaseSRWLockExclusive(&g_dec_live_lock);
    if (on && !done) printf("movie: WARNING all %d live-decoder slots are taken: this decoder is not listed and every call to it returns 0x%x\n", MAX_LIVE_DEC, ST_INVALID);
    return done;
}

static void release_pending(Ext *e) {                 /* the current sample is done with (Advance) */
    if (e->have_pending && !e->pend_consumed && e->pending) IMFSample_Release(e->pending);
    if (e->have_pending) { e->ahead[e->pend_track].have = 0; e->ahead[e->pend_track].s = NULL; }
    e->have_pending = 0; e->pending = NULL; e->pend_consumed = 0;
}
static void release_ahead(Ext *e, int track) {        /* track < 0: all */
    for (int i = 0; i < MAX_TRACKS; i++) {
        if (track >= 0 && i != track) continue;
        if (e->have_pending && e->pend_track == i) continue;                  /* owned by release_pending */
        if (e->ahead[i].have && e->ahead[i].s) IMFSample_Release(e->ahead[i].s);
        e->ahead[i].have = 0; e->ahead[i].s = NULL;
    }
}

#ifdef MOVIE_FFMPEG
/* The FFmpeg fallback's reader over a copy of the file (e->bs and e->rd must be free). */
static HRESULT ext_open_reader_ffmpeg(Ext *e, const unsigned char *data, size_t size) {
    IStream *st = ffmf_SHCreateMemStream(data, (UINT)size);
    if (!st) return E_OUTOFMEMORY;
    HRESULT hr = ffmf_MFCreateMFByteStreamOnStream(st, &e->bs);
    ffmf_IStream_Release(st);
    if (FAILED(hr)) return hr;
    hr = ffmf_MFCreateSourceReaderFromByteStream(e->bs, NULL, &e->rd);
    if (FAILED(hr)) { IMFByteStream_Release(e->bs); e->bs = NULL; e->rd = NULL; }
    return hr;
}
#endif
/* Media Foundation's reader over a copy of the file (e->bs stays set on failure, as before: the destructor frees it). */
static HRESULT ext_open_reader_mf(Ext *e, unsigned char *data, size_t size) {
    HRESULT hr;
    if (!movie_mf_present()) return (HRESULT)0xc00d36c4;     /* as when it cannot open WebM: the fallback, or the notice */
    IStream *st = SHCreateMemStream(data, (UINT)size);
    if (!st) { printf("movie: SHCreateMemStream failed (%zu bytes)\n", size); return E_OUTOFMEMORY; }
    hr = MFCreateMFByteStreamOnStream(st, &e->bs);
    IStream_Release(st);
    if (FAILED(hr)) { printf("movie: MFCreateMFByteStreamOnStream %08lx\n", hr); return hr; }
    IMFAttributes *ba = NULL;
    if (SUCCEEDED(IMFByteStream_QueryInterface(e->bs, &IID_IMFAttributes, (void **)&ba))) {
        const char *ext = strrchr(e->path, '.');
        const WCHAR *ctype = ext && _stricmp(ext, ".mp4") == 0 ? L"video/mp4" : ext && _stricmp(ext, ".mkv") == 0 ? L"video/x-matroska" : L"video/webm";
        IMFAttributes_SetString(ba, &MF_BYTESTREAM_CONTENT_TYPE, ctype);
        WCHAR name[64]; swprintf(name, 64, L"movie%hs", ext ? ext : ".webm");
        IMFAttributes_SetString(ba, &MF_BYTESTREAM_ORIGIN_NAME, name);
        IMFAttributes_Release(ba);
    }
    hr = MFCreateSourceReaderFromByteStream(e->bs, NULL, &e->rd);
#ifdef MOVIE_FFMPEG
    if (SUCCEEDED(hr) && ffmf_test() == 1) { IMFSourceReader_Release(e->rd); e->rd = NULL; hr = (HRESULT)0xc00d36c4; }   /* TEST ONLY */
#endif
    if (FAILED(hr)) printf("movie: MFCreateSourceReaderFromByteStream %08lx\n", hr);
    return hr;
}

static int ext_probe_tracks(Ext *e, size_t size);
static int ext_open_bytes(Ext *e, unsigned char *data, size_t size) {
    com_init();
    HRESULT hr;
#ifdef MOVIE_FFMPEG
    if (ffmf_forced()) {
        hr = ext_open_reader_ffmpeg(e, data, size);
        printf("movie: SSBU_MOVIE_FFMPEG=1: the FFmpeg fallback opens %s: %08lx\n", e->path, hr);
    } else {
        hr = ext_open_reader_mf(e, data, size);
        if (FAILED(hr) && ffmf_allowed()) {
            HRESULT mf = hr;
            if (e->bs) { IMFByteStream_Release(e->bs); e->bs = NULL; }
            e->rd = NULL;
            hr = ext_open_reader_ffmpeg(e, data, size);
            printf("movie: Media Foundation cannot open %s (%08lx): the FFmpeg fallback %s (%08lx)\n", e->path, mf, SUCCEEDED(hr) ? "plays it" : "cannot either", hr);
            if (FAILED(hr)) hr = mf;
        }
    }
#else
    hr = ext_open_reader_mf(e, data, size);
#endif
    if (FAILED(hr)) {
        if (hr == (HRESULT)0xc00d36c4) {      /* MF_E_UNSUPPORTED_BYTESTREAM_TYPE: Windows cannot open WebM at all -> the game waits on a black movie screen */
            void menu_notice(const char *text);
            printf("movie: Windows has no WebM support: install 'Web Media Extensions' and 'VP9 Video Extensions' from the Microsoft Store "
                   "(Windows N editions: also the Media Feature Pack), then start the game again\n");
            menu_notice("The game's movies cannot play on this PC, so it stays on a black screen.\n\n"
                        "Install from the Microsoft Store (free): Web Media Extensions and VP9 Video Extensions\n"
                        "(Windows 'N' editions also need the Media Feature Pack), then start the game again.");
        }
        return 0;
    }
    return ext_probe_tracks(e, size);
}

/* The tracks of the reader just opened, into e->tr (none selected). */
static int ext_probe_tracks(Ext *e, size_t size) {

    PROPVARIANT var; PropVariantInit(&var);
    if (SUCCEEDED(IMFSourceReader_GetPresentationAttribute(e->rd, (DWORD)MF_SOURCE_READER_MEDIASOURCE, &MF_PD_DURATION, &var)) && var.vt == VT_UI8)
        e->duration_us = (int64_t)(var.uhVal.QuadPart / 10);
    PropVariantClear(&var);
    IMFSourceReader_SetStreamSelection(e->rd, (DWORD)MF_SOURCE_READER_ALL_STREAMS, FALSE);   /* the game selects what it decodes */
    e->ntracks = 0;
    for (DWORD i = 0; i < MAX_TRACKS; i++) {
        IMFMediaType *t = NULL;
        if (FAILED(IMFSourceReader_GetNativeMediaType(e->rd, i, 0, &t))) break;
        Track *tr = &e->tr[e->ntracks++];
        memset(tr, 0, sizeof *tr);
        GUID major, sub;
        IMFMediaType_GetGUID(t, &MF_MT_MAJOR_TYPE, &major);
        IMFMediaType_GetGUID(t, &MF_MT_SUBTYPE, &sub);
        uint32_t fcc = is_mf_fourcc_guid(&sub) ? sub.Data1 : 0;
        tr->fourcc = fcc;
        if (IsEqualGUID(&major, &MFMediaType_Video)) {
            UINT64 fs = 0, fr = 0;
            tr->kind = 0;
            IMFMediaType_GetUINT64(t, &MF_MT_FRAME_SIZE, &fs);
            IMFMediaType_GetUINT64(t, &MF_MT_FRAME_RATE, &fr);
            tr->w = (int)(fs >> 32); tr->h = (int)(uint32_t)fs;
            tr->fps = (uint32_t)fr ? (double)(fr >> 32) / (double)(uint32_t)fr : 0.0;
            strcpy(tr->mime, fcc == FCC('V', 'P', '9', '0') ? "video/x-vnd.on2.vp9" : fcc == FCC('V', 'P', '8', '0') ? "video/x-vnd.on2.vp8" :
                             fcc == FCC('H', '2', '6', '4') || fcc == FCC('A', 'V', 'C', '1') ? "video/avc" : fcc == FCC('H', 'E', 'V', 'C') ? "video/hevc" : "video/unknown");
        } else if (IsEqualGUID(&major, &MFMediaType_Audio)) {
            UINT32 rate = 0, ch = 0;
            tr->kind = 1;
            IMFMediaType_GetUINT32(t, &MF_MT_AUDIO_SAMPLES_PER_SECOND, &rate);
            IMFMediaType_GetUINT32(t, &MF_MT_AUDIO_NUM_CHANNELS, &ch);
            tr->rate = (int)rate; tr->ch = (int)ch;
            strcpy(tr->mime, IsEqualGUID(&sub, &GUID_Vorbis) ? "audio/vorbis" : fcc == 0x704F ? "audio/opus" : fcc == 0x1610 ? "audio/mp4a-latm" :
                             fcc == 0x55 ? "audio/mpeg" : fcc == 1 ? "audio/raw" : "audio/unknown");
        } else {
            tr->kind = 2;
            strcpy(tr->mime, "application/octet-stream");
        }
        IMFMediaType_Release(t);
    }
    printf("movie: opened %s: %zu bytes, %.1f s, %d tracks:", e->path, size, e->duration_us / 1e6, e->ntracks);
    for (int i = 0; i < e->ntracks; i++) {
        Track *tr = &e->tr[i];
        if (tr->kind == 0) printf("  [%d] %s %dx%d %.2f fps", i, tr->mime, tr->w, tr->h, tr->fps);
        else if (tr->kind == 1) printf("  [%d] %s %d Hz %d ch", i, tr->mime, tr->rate, tr->ch);
        else printf("  [%d] %s", i, tr->mime);
    }
    printf("\n");
    return 1;
}

#ifdef MOVIE_FFMPEG
/* Media Foundation opened the movie but cannot decode it (no decoder for track `track`, or the first read failed): the
 * same file goes to the FFmpeg fallback, read back from the byte stream, and the tracks selected so far are selected
 * there again. Only before any sample was handed out. 1 when done. Caller holds the lock. */
static int ext_select(Ext *e, int i, int on);
static int ext_switch_to_ffmpeg(Ext *e, int track, HRESULT why) {
    if (!e->rd || !e->bs || FFMF_IS(e->rd) || e->samples_read || !ffmf_allowed()) return 0;
    QWORD len = 0;
    if (FAILED(IMFByteStream_GetLength(e->bs, &len)) || !len || len > ((QWORD)2 << 30)) return 0;
    unsigned char *data = malloc((size_t)len);
    QWORD off = 0;
    if (data && SUCCEEDED(IMFByteStream_SetCurrentPosition(e->bs, 0)))
        while (off < len) {
            ULONG got = 0, want = len - off > (1u << 24) ? (1u << 24) : (ULONG)(len - off);
            if (FAILED(IMFByteStream_Read(e->bs, data + off, want, &got)) || !got) break;
            off += got;
        }
    if (!data || off != len) { printf("movie: %s: the file cannot be read back for the FFmpeg fallback\n", e->path); free(data); return 0; }
    IMFSourceReader *mf_rd = e->rd;
    IMFByteStream *mf_bs = e->bs;
    release_pending(e);
    release_ahead(e, -1);
    e->rd = NULL; e->bs = NULL;
    HRESULT hr = ext_open_reader_ffmpeg(e, data, (size_t)len);
    free(data);
    int n = 0;
    if (SUCCEEDED(hr))
        for (IMFMediaType *t = NULL; n < MAX_TRACKS && SUCCEEDED(IMFSourceReader_GetNativeMediaType(e->rd, (DWORD)n, 0, &t)); n++) IMFMediaType_Release(t);
    if (FAILED(hr) || n != e->ntracks) {
        printf("movie: %s: the FFmpeg fallback cannot take it over (%08lx, %d tracks for %d)\n", e->path, hr, n, e->ntracks);
        if (e->rd) IMFSourceReader_Release(e->rd);
        if (e->bs) IMFByteStream_Release(e->bs);
        e->rd = mf_rd; e->bs = mf_bs;
        return 0;
    }
    IMFSourceReader_Release(mf_rd);
    IMFByteStream_Release(mf_bs);
    if (track >= 0) printf("movie: %s: Media Foundation cannot decode track %d (%s, %08lx): the FFmpeg fallback plays this movie\n", e->path, track, e->tr[track].mime, why);
    else printf("movie: %s: Media Foundation's first read failed (%08lx): the FFmpeg fallback plays this movie\n", e->path, why);
    IMFSourceReader_SetStreamSelection(e->rd, (DWORD)MF_SOURCE_READER_ALL_STREAMS, FALSE);
    for (int j = 0; j < e->ntracks; j++) {
        e->tr[j].eos = 0; e->tr[j].failed = 0;
        if (e->tr[j].selected && j != track) { e->tr[j].selected = 0; ext_select(e, j, 1); }
    }
    e->eos = 0;
    return 1;
}
#endif

static int ext_select(Ext *e, int i, int on) {
    if (!e->rd || i < 0 || i >= e->ntracks) return ST_INVALID;
    Track *tr = &e->tr[i];
    HRESULT hr = IMFSourceReader_SetStreamSelection(e->rd, (DWORD)i, on ? TRUE : FALSE);
    if (on && SUCCEEDED(hr) && tr->kind != 2) {
        IMFMediaType *t = NULL;
        new_media_type(e->rd, &t);
        if (tr->kind == 0) {
            IMFMediaType_SetGUID(t, &MF_MT_MAJOR_TYPE, &MFMediaType_Video);
            IMFMediaType_SetGUID(t, &MF_MT_SUBTYPE, &MFVideoFormat_NV12);
        } else {
            IMFMediaType_SetGUID(t, &MF_MT_MAJOR_TYPE, &MFMediaType_Audio);
            IMFMediaType_SetGUID(t, &MF_MT_SUBTYPE, &MFAudioFormat_PCM);
            IMFMediaType_SetUINT32(t, &MF_MT_AUDIO_BITS_PER_SAMPLE, 16);
            IMFMediaType_SetUINT32(t, &MF_MT_AUDIO_SAMPLES_PER_SECOND, (UINT32)tr->rate);
            IMFMediaType_SetUINT32(t, &MF_MT_AUDIO_NUM_CHANNELS, (UINT32)tr->ch);
        }
        hr = IMFSourceReader_SetCurrentMediaType(e->rd, (DWORD)i, NULL, t);
        IMFMediaType_Release(t);
        if (FAILED(hr) && tr->kind == 1) {            /* let the reader pick the PCM layout */
            new_media_type(e->rd, &t);
            IMFMediaType_SetGUID(t, &MF_MT_MAJOR_TYPE, &MFMediaType_Audio);
            IMFMediaType_SetGUID(t, &MF_MT_SUBTYPE, &MFAudioFormat_PCM);
            hr = IMFSourceReader_SetCurrentMediaType(e->rd, (DWORD)i, NULL, t);
            IMFMediaType_Release(t);
        }
#ifdef MOVIE_FFMPEG
        if (ffmf_test() == 2 && !FFMF_IS(e->rd)) hr = MF_E_TOPO_CODEC_NOT_FOUND;     /* TEST ONLY: no Media Foundation decoder */
#endif
        if (SUCCEEDED(hr)) {
            IMFMediaType *cur = NULL;
            if (SUCCEEDED(IMFSourceReader_GetCurrentMediaType(e->rd, (DWORD)i, &cur))) {
                if (tr->kind == 0) { UINT64 fs = 0; IMFMediaType_GetUINT64(cur, &MF_MT_FRAME_SIZE, &fs); if (fs) { tr->w = (int)(fs >> 32); tr->h = (int)(uint32_t)fs; } }
                else { UINT32 v = 0; if (SUCCEEDED(IMFMediaType_GetUINT32(cur, &MF_MT_AUDIO_SAMPLES_PER_SECOND, &v))) tr->rate = (int)v; if (SUCCEEDED(IMFMediaType_GetUINT32(cur, &MF_MT_AUDIO_NUM_CHANNELS, &v))) tr->ch = (int)v; }
                IMFMediaType_Release(cur);
            }
        } else {
#ifdef MOVIE_FFMPEG
            if (ext_switch_to_ffmpeg(e, i, hr)) return ext_select(e, i, on);
#endif
            printf("movie: track %d (%s): no Media Foundation decoder path to %s (%08lx); track left unselected\n", i, tr->mime, tr->kind == 0 ? "NV12" : "PCM", hr);
            if (tr->kind == 1 && strcmp(tr->mime, "audio/vorbis") == 0) vorbis_hint();
            IMFSourceReader_SetStreamSelection(e->rd, (DWORD)i, FALSE);
            return ST_UNSUPPORTED;
        }
    }
    if (e->have_pending && e->pend_track == i) release_pending(e);
    release_ahead(e, i);
    tr->selected = on && SUCCEEDED(hr);
    tr->eos = 0;
    printf("movie: %s track %d (%s)%s\n", on ? "selected" : "unselected", i, tr->mime, SUCCEEDED(hr) ? "" : " FAILED");
    return SUCCEEDED(hr) ? ST_OK : ST_FAILED;
}

/* The current sample of the extractor, as NuMediaExtractor defines it: the one with the SMALLEST TIMESTAMP among the
 * next samples of the selected tracks (file order). Each selected track is read ahead by one decoded sample with its
 * own ReadSample(stream) call; reading "any stream" instead hands samples out in the order the decoders finish them,
 * which changes from run to run - and the game's two feed threads each wait for THEIR track to be the current one, so
 * a burst of one track fills that decoder's buffers and starves the other (the start-up stall).
 * Returns 0 with a pending sample, or ST_END. Caller holds the lock. */
static int ext_fill(Ext *e) {
    if (e->have_pending) return ST_OK;
    {   /* TEST ONLY, SSBU_SKIP_MOVIES=1 (tests\DEBUG_MODE.md): every movie ends at once, as a stream with no samples left */
        static int skip = -1;
        if (skip < 0) { const char *v = getenv("SSBU_SKIP_MOVIES"); skip = v && atoi(v) != 0; }
        static unsigned long long keep = 0;                /* SSBU_SKIP_MOVIES=<n>: n > 1 lets the first n samples through (default 1 = 12) */
        if (skip > 0 && !keep) { const char *v = getenv("SSBU_SKIP_MOVIES"); keep = atoi(v) > 1 ? (unsigned long long)atoi(v) : 12; }
        /* counted from the last SeekTo: the game seeks (to 0) again when its movie start is late (slow PC, threads
         * held); the samples read before are refused as stale, so a budget counted from the open left the stream with
         * no valid sample after such a seek (audio never started, the title screen never came: run-ahead / PR #46 hang) */
        if (skip && e->samples_read - e->seek_base >= keep) { if (!e->eos) printf("movie: SSBU_SKIP_MOVIES: end of stream after %llu samples%c", e->samples_read, 10); e->eos = 1; e->skip_eos = 1;
            {   /* TEST ONLY (hs13), SSBU_MOVIE_TEST_RESYNC_AT_EOS=<flag>: the game's resync request raised at this early end of stream */
                static int f = -1; if (f < 0) { const char *v = getenv("SSBU_MOVIE_TEST_RESYNC_AT_EOS"); f = v ? atoi(v) : 0; }
                static int done; if (f > 0 && !done) { done = 1; InterlockedOr8((char *)(uintptr_t)GA(0x7107446040ULL), (char)f); printf("movie: TEST: resync request %d raised at the early end of stream%c", f, 10); }
            }
            return ST_END; }
    }
    if (e->eos || !e->rd) return ST_END;
    int best = -1;
    for (int i = 0; i < e->ntracks; i++) {
        Track *tr = &e->tr[i];
        if (!tr->selected) continue;
        for (int guard = 0; !e->ahead[i].have && !tr->eos && guard < 256; guard++) {
            DWORD idx = 0, flags = 0; LONGLONG ts = 0; IMFSample *s = NULL;
            HRESULT hr = IMFSourceReader_ReadSample(e->rd, (DWORD)i, 0, &idx, &flags, &ts, &s);
#ifdef MOVIE_FFMPEG
            if (ffmf_test() == 3 && !FFMF_IS(e->rd)) { if (s) IMFSample_Release(s); s = NULL; hr = E_FAIL; }    /* TEST ONLY: a broken decoder */
#endif
            {   /* test: SSBU_MOVIE_FAIL_AT=<n> makes the read after n samples fail */
                static int fail_at = -1;
                if (fail_at < 0) { const char *v = getenv("SSBU_MOVIE_FAIL_AT"); fail_at = v ? atoi(v) : 0; }
                if (fail_at > 0 && e->samples_read >= (unsigned long long)fail_at) { if (s) { IMFSample_Release(s); s = NULL; } hr = E_FAIL; }
            }
            if (FAILED(hr) || (flags & MF_SOURCE_READERF_ERROR)) {
#ifdef MOVIE_FFMPEG
                if (!e->samples_read && !FFMF_IS(e->rd)) {
                    if (s) { IMFSample_Release(s); s = NULL; }
                    if (ext_switch_to_ffmpeg(e, -1, FAILED(hr) ? hr : E_FAIL)) return ext_fill(e);
                }
#endif
                tr->failed = 1;                           /* the decoder of this track reports it: dec_error_check */
                printf("movie: ReadSample(track %d) failed (%08lx, flags %lx) after %llu samples: treating as its end\n", i, hr, flags, e->samples_read);
                if (s) IMFSample_Release(s);
                tr->eos = 1;
                break;
            }
            if (flags & MF_SOURCE_READERF_ENDOFSTREAM) { if (s) IMFSample_Release(s); tr->eos = 1; break; }
            if (!s) continue;                             /* a tick or a format change without data */
            e->ahead[i].have = 1; e->ahead[i].s = s; e->ahead[i].us = ts / 10;
            e->samples_read++;
        }
        if (e->ahead[i].have && (best < 0 || e->ahead[i].us < e->ahead[best].us)) best = i;
    }
    if (best < 0) { if (!e->eos) printf("movie: end of stream after %llu samples\n", e->samples_read); e->eos = 1; return ST_END; }
    e->have_pending = 1; e->pending = e->ahead[best].s; e->pend_track = best; e->pend_us = e->ahead[best].us; e->pend_consumed = 0;
    return ST_OK;
}

/* ---------------------------------------------------------------- Extractor virtual functions */
static void ext_dtor_common(Ctx *c, int deleting) {
    Ext *e = ext_of(A0);
    if (e) {
        ext_lock(e);
        release_pending(e);
        release_ahead(e, -1);
        if (e->rd) IMFSourceReader_Release(e->rd);
        if (e->bs) IMFByteStream_Release(e->bs);
        e->rd = NULL; e->bs = NULL;
        ext_unlock(e);
        DeleteCriticalSection(&e->cs);
        printf("movie: Extractor destroyed (%llu samples read)\n", e->samples_read);
        free(e);
        wr64(A0 + 8, 0);
    }
    if (deleting) gcall(c, GAME_FREE, A0, 0, 0, 0, 0);       /* the game allocated the 16-byte object with f_710392dce0 [game 0x71036f1ccc] */
}
static void ext_dtor(Ctx *c) { ext_dtor_common(c, 0); }
static void ext_deleting_dtor(Ctx *c) { ext_dtor_common(c, 1); }

static int ext_set_source_bytes(Ext *e, unsigned char *data, size_t size) {
    const char *save = getenv("SSBU_MOVIE_SAVE");
    if (save) { FILE *f = fopen(save, "wb"); if (f) { fwrite(data, 1, size, f); fclose(f); printf("movie: saved %zu bytes to %s\n", size, save); } }
    int ok = ext_open_bytes(e, data, size);
    free(data);
    return ok ? ST_OK : ST_FAILED;
}

static void ext_SetDataSource_reader(Ctx *c) {       /* (ClientStreamReader *reader, const char *path) */
    Ext *e = ext_of(A0);
    uint64_t reader = A1;
    const char *path = (const char *)(uintptr_t)A2;
    if (!e || !reader) { RET(ST_INVALID); return; }
    strncpy(e->path, path ? path : "", sizeof e->path - 1);
    uint64_t vt = rd64(reader);
    uint64_t handle = 0;
    uint64_t ok = gcall(c, rd64(vt + 0x10), reader, (uint64_t)(uintptr_t)path, (uint64_t)(uintptr_t)&handle, 0, 0);
    if (!(ok & 1)) { printf("movie: SetDataSource(%s): the game's reader could not open it\n", path); RET(ST_FAILED); return; }
    int64_t size = 0;
    uint64_t r = gcall(c, rd64(vt + 0x28), reader, handle, (uint64_t)(uintptr_t)&size, 0, 0);
    if (size <= 0 || size > (int64_t)2 << 30) {       /* the SDK ignores GetSize's return value [subsdk 0x1d93dc] */
        printf("movie: SetDataSource(%s): GetSize -> %llx, size %lld\n", path, (unsigned long long)r, (long long)size);
        gcall(c, rd64(vt + 0x20), reader, handle, 0, 0, 0);
        RET(ST_FAILED); return;
    }
    unsigned char *data = malloc((size_t)size);
    if (!data) { gcall(c, rd64(vt + 0x20), reader, handle, 0, 0, 0); RET(ST_FAILED); return; }
    int64_t got = 0;
    LARGE_INTEGER f0, t0, t1; QueryPerformanceFrequency(&f0); QueryPerformanceCounter(&t0);
    while (got < size) {
        uint64_t chunk = (uint64_t)(size - got) < (8u << 20) ? (uint64_t)(size - got) : (8u << 20);
        int64_t n = (int64_t)gcall(c, rd64(vt + 0x18), reader, handle, (uint64_t)got, (uint64_t)(uintptr_t)(data + got), chunk);
        if (n <= 0) break;
        got += n;
    }
    QueryPerformanceCounter(&t1);
    gcall(c, rd64(vt + 0x20), reader, handle, 0, 0, 0);
    printf("movie: SetDataSource(%s): read %lld of %lld bytes through the game's reader in %.2f s\n", path, (long long)got, (long long)size,
           (double)(t1.QuadPart - t0.QuadPart) / f0.QuadPart);
    if (got != size) { free(data); RET(ST_FAILED); return; }
    if (g_test_resync_flag && g_test_resync_at == 0) {   /* SSBU_MOVIE_TEST_RESYNC=<flag>,0: raised here, before any decoder exists */
        InterlockedOr8((char *)(uintptr_t)GA(0x7107446040ULL), (char)g_test_resync_flag);
        printf("movie: TEST: resync request %d raised at SetDataSource\n", g_test_resync_flag);
    }
    RET(ext_set_source_bytes(e, data, (size_t)size));
}

static void ext_SetDataSource_path(Ctx *c) {         /* (const char *path): a host file, for tests */
    Ext *e = ext_of(A0);
    const char *path = (const char *)(uintptr_t)A1;
    if (!e || !path) { RET(ST_INVALID); return; }
    strncpy(e->path, path, sizeof e->path - 1);
    FILE *f = fopen(path, "rb");
    if (!f) { printf("movie: SetDataSource(%s): not a host file\n", path); RET(ST_FAILED); return; }
    fseek(f, 0, SEEK_END); long sz = ftell(f); fseek(f, 0, SEEK_SET);
    unsigned char *data = malloc((size_t)sz);
    size_t got = fread(data, 1, (size_t)sz, f);
    fclose(f);
    RET(got == (size_t)sz ? ext_set_source_bytes(e, data, got) : ST_FAILED);
}

static void ext_SetDataSource_mem(Ctx *c) {          /* (const void *data, int size) */
    Ext *e = ext_of(A0);
    if (!e || !A1 || (int)A2 <= 0) { RET(ST_INVALID); return; }
    strcpy(e->path, "memory.webm");
    unsigned char *data = malloc((size_t)(int)A2);
    memcpy(data, (void *)(uintptr_t)A1, (size_t)(int)A2);
    RET(ext_set_source_bytes(e, data, (size_t)(int)A2));
}

static void ext_GetTrackCount(Ctx *c) { Ext *e = ext_of(A0); if (!e || !A1) { RET(ST_INVALID); return; } wr32(A1, (uint32_t)(e->rd ? e->ntracks : 0)); RET(e->rd ? ST_OK : ST_FAILED); }

static void ext_GetTrackConfiguration(Ctx *c) {       /* (int track, MediaData *out) */
    Ext *e = ext_of(A0);
    int i = (int)A1;
    MD *m = md_of(A2);
    if (!e || !m) { RET(ST_INVALID); return; }
    if (!e->rd || i < 0 || i >= e->ntracks) { RET(ST_INVALID); return; }
    Track *tr = &e->tr[i];
    md_clear(m);
    md_set_str(m, "mime", tr->mime);
    md_set_i64(m, "durationUs", e->duration_us);
    md_set_i32(m, "max-input-size", 0x10000);
    if (tr->kind == 0) {
        md_set_i32(m, "width", tr->w); md_set_i32(m, "height", tr->h);
        md_set_i32(m, "frame-rate", (int)(tr->fps + 0.5));
    } else if (tr->kind == 1) {
        md_set_i32(m, "sample-rate", tr->rate); md_set_i32(m, "channel-count", tr->ch);
    }
    md_set_ptr(m, "nn-extractor", (uint64_t)(uintptr_t)e);    /* lets the decoder find its source */
    md_set_i32(m, "nn-track", i);
    if (g_log) printf("movie: GetTrackConfiguration(%d) -> %s\n", i, tr->mime);
    RET(ST_OK);
}

static void ext_SelectTrack(Ctx *c) { Ext *e = ext_of(A0); if (!e) { RET(ST_INVALID); return; } ext_lock(e); int r = ext_select(e, (int)A1, 1); ext_unlock(e); RET(r); }
static void ext_UnselectTrack(Ctx *c) { Ext *e = ext_of(A0); if (!e) { RET(ST_INVALID); return; } ext_lock(e); int r = ext_select(e, (int)A1, 0); ext_unlock(e); RET(r); }

/* (R3 hs13, the boots that missed the title screen: tm4, hw1, tw6h, ~1 in 4 when two games boot at once) The game's movie Seek
 * [0x71036e7620] flushes and restarts the decoders only when the player state is >= 4 (playing); in state 3 (prepared, the
 * boot-time resync seek of a late movie start, more frequent on a loaded PC) it calls Extractor::SeekTo alone. With
 * SSBU_SKIP_MOVIES the end of stream comes after 12 samples, i.e. possibly while the player is still prepared: the decoders
 * had taken the end-of-stream input, so (as MediaCodec) they offered no input buffer again, the game's feed threads waited
 * for ever after the SeekTo, the movie never ended. A real movie never ends that early. Now, after a seek that follows
 * such an early (skip) end of stream, every decoder of this extractor that took the end of stream is flushed and offers
 * all its inputs again (what Flush + Start would do). SSBU_MOVIE_SKIP_REARM=0: the old way (test). */
static void dec_release_all(Dec *d);
static void skip_rearm(Ext *e) {
    static int on = -1;
    if (on < 0) { const char *v = getenv("SSBU_MOVIE_SKIP_REARM"); on = !(v && v[0] == '0'); }
    if (!on) return;
    Dec *list[MAX_LIVE_DEC]; int n = 0;
    AcquireSRWLockShared(&g_dec_live_lock);
    for (int i = 0; i < MAX_LIVE_DEC; i++) if (g_dec_live[i] && ((Dec *)g_dec_live[i])->ext == e) list[n++] = (Dec *)g_dec_live[i];
    ReleaseSRWLockShared(&g_dec_live_lock);
    for (int k = 0; k < n; k++) {
        Dec *d = list[k];
        EnterCriticalSection(&d->cs);
        int re = !d->dead && d->eos_in;
        if (re) {
            dec_release_all(d);
            for (int i = 0; i < d->nin; i++) { d->in_state[i] = IN_OFFERED; d->in_list[i] = i; }
            d->in_n = d->nin;
        }
        LeaveCriticalSection(&d->cs);
        if (re) { printf("movie: SSBU_SKIP_MOVIES: seek after the early end of stream: %s decoder offers its inputs again (the game did not flush it)\n", d->is_video ? "video" : "audio"); signal_event(d, 0); }
    }
}
static void ext_SeekTo(Ctx *c) {                      /* (int64 timeUs) */
    Ext *e = ext_of(A0);
    if (!e || !e->rd) { RET(ST_INVALID); return; }
    ext_lock(e);
    int rearm = e->skip_eos; e->skip_eos = 0;
    release_pending(e);
    release_ahead(e, -1);
    e->gen++;
    e->seek_base = e->samples_read;
    PROPVARIANT var; PropVariantInit(&var);
    var.vt = VT_I8; var.hVal.QuadPart = (LONGLONG)A1 * 10;
    HRESULT hr = IMFSourceReader_SetCurrentPosition(e->rd, &GUID_NULL, &var);
    e->eos = 0;
    for (int i = 0; i < e->ntracks; i++) e->tr[i].eos = 0;
    ext_unlock(e);
    printf("movie: SeekTo(%.3f s) %08lx (tick %llu)\n", (int64_t)A1 / 1e6, hr, (unsigned long long)GetTickCount64());
    if (rearm) skip_rearm(e);
    RET(SUCCEEDED(hr) ? ST_OK : ST_FAILED);
}

/* (V 2026-10-22, the opening movie black for ~40 s after the boot resync seek) The game's two feed threads [game 0x71036f6c20
 * video, 0x71036f4240 audio] each keep a list of the input indices the decoder event handler acquired [handler 0x71036f3710:
 * AcquireInputBufferIndex, push to the list (0x71036f6e80), message 1]; every 1 ms (or per message) one feed step
 * [0x71036f6ce0] asks GetTrackIndexForAvailableData and, when the next sample is its own track, pops an index and does
 * GetInputBuffer / Read / GetSampleTime / SendInputBufferForDecode / Advance. The game's Seek [0x71036e7620] (player state
 * >= 4) does Flush x2, posts "empty your list" to both feed threads (message 3 video, 5 audio), SeekTo, sleeps 16 ms, posts it
 * again, then Start x2. The list is emptied when the feed thread RECEIVES that message, i.e. asynchronously. On the console a
 * feed step is quick (MediaCodec decodes elsewhere). Here Media Foundation decodes inside ReadSample (ext_fill), so a feed
 * thread can be inside one step for a long time (the first VP9 pictures on a busy PC; SSBU_MOVIE_TEST_VIDEO_DELAY in the
 * test): the "empty" messages are then received AFTER Start, after the handler had already pushed the indices Start offered,
 * and they wipe them. The decoder believes the game holds all its inputs, the game's list is empty: no video input for ever,
 * and since the extractor's next sample stays a video one, no audio either (24-draw black frames, until a second seek
 * flushes and restarts everything). Proof: n11_mvs1 (SeekTo while the first sample was held, then no SendInput at all).
 * Detection (exact, no game address): a feed step that got its own track and did NOT call GetInputBuffer before the same
 * thread's next GetTrackIndexForAvailableData found its list empty. If at that point the decoder of that track still counts
 * indices as held by the game for more than RESCUE_MS (an index normally goes acquire -> list -> pop within a millisecond),
 * they were lost with the list: they are offered again (input event), as Start would have. SSBU_MOVIE_RESCUE=0: off (test). */
#define RESCUE_MS 100
static __declspec(thread) Ext *t_gti_ext;             /* this thread's last GetTrackIndexForAvailableData: extractor, */
static __declspec(thread) int t_gti_track = -1;       /* the track it returned (-1 none / not ok), */
static __declspec(thread) int t_gti_fed;              /* and whether a GetInputBuffer followed */
static void feeder_found_empty(Ext *e, int track) {
    static int on = -1;
    if (on < 0) { const char *v = getenv("SSBU_MOVIE_RESCUE"); on = !(v && v[0] == '0'); }
    if (!on) return;
    Dec *d = NULL;
    DWORD me = GetCurrentThreadId();
    AcquireSRWLockShared(&g_dec_live_lock);
    for (int i = 0; i < MAX_LIVE_DEC && !d; i++) {
        Dec *x = (Dec *)g_dec_live[i];
        if (x && x->ext == e && x->track == track && !x->h264 && x->feeder_tid == me) d = x;
    }
    ReleaseSRWLockShared(&g_dec_live_lock);
    if (!d) return;                                   /* not the feed thread of that track (the other one, which skips it) */
    ULONGLONG now = GetTickCount64();
    int n = 0;
    EnterCriticalSection(&d->cs);
    if (!d->dead && d->started && !d->eos_in) {
        for (int i = 0; i < d->nin; i++) {
            if (d->in_state[i] != IN_CLIENT || now - d->client_since[i] < RESCUE_MS) continue;
            Token t; memcpy(&t, d->mem + (size_t)i * d->slot, sizeof t);    /* (none expected: Send clears the slot) */
            if (t.magic == TOKEN_MAGIC && t.s) IMFSample_Release(t.s);
            memset(d->mem + (size_t)i * d->slot, 0, d->slot);
            d->in_state[i] = IN_OFFERED; d->in_list[d->in_n++] = i;
            n++;
        }
        d->rescued += (unsigned long long)n;
    }
    LeaveCriticalSection(&d->cs);
    if (!n) return;
    printf("movie: Decoder(%s): the game's feed thread has no input index left while %d acquired ones were never sent (its list was emptied late, after a seek's Start): offered again (tick %llu)\n",
           d->is_video ? "video" : "audio", n, (unsigned long long)now);
    signal_event(d, 0);
}
static void ext_GetTrackIndexForAvailableData(Ctx *c) {   /* (size_t *track) */
    Ext *e = ext_of(A0);
    if (!e || !A1) { RET(ST_INVALID); return; }
    if (t_gti_ext == e && t_gti_track >= 0 && !t_gti_fed) feeder_found_empty(e, t_gti_track);
    ext_lock(e);
    int r = ext_fill(e);
    int tr = r == ST_OK ? e->pend_track : -1;
    if (r == ST_OK) wr64(A1, (uint64_t)e->pend_track);
    ext_unlock(e);
    t_gti_ext = e; t_gti_track = tr; t_gti_fed = 0;
    RET(r);
}

static void ext_Read(Ctx *c) {                        /* (Buffer *out): the sample token goes into the decoder's input slot */
    Ext *e = ext_of(A0);
    uint64_t b = A1;
    if (!e || !b) { RET(ST_INVALID); return; }
    ext_lock(e);
    int r = ext_fill(e);
    if (r == ST_OK) {
        uint64_t base = rd64(b + B_BASE), cap = rd64(b + B_CAP);
        if (base && cap >= sizeof(Token) && !e->pend_consumed) {
            Token t = {TOKEN_MAGIC, e->pending, e->pend_us, e->gen};
            memcpy((void *)(uintptr_t)base, &t, sizeof t);
            wr32(b + B_OFFSET, 0);
            wr32(b + B_SIZE, (uint32_t)sizeof t);
            wr64(b + B_I64, (uint64_t)e->pend_us);
            e->pend_consumed = 1;                     /* the sample now belongs to the token */
        } else {
            r = ST_FAILED;
        }
    }
    ext_unlock(e);
    RET(r);
}

static void ext_Advance(Ctx *c) {
    Ext *e = ext_of(A0);
    if (!e) { RET(ST_INVALID); return; }
    ext_lock(e);
    release_pending(e);
    ext_unlock(e);
    RET(ST_OK);
}

static void ext_GetSampleTime(Ctx *c) {               /* (int64 *timeUs) */
    Ext *e = ext_of(A0);
    if (!e || !A1) { RET(ST_INVALID); return; }
    ext_lock(e);
    int r = e->have_pending ? ST_OK : ext_fill(e);
    wr64(A1, (uint64_t)(r == ST_OK ? e->pend_us : -1));
    ext_unlock(e);
    RET(r);
}

static void ext_GetSampleMetaData(Ctx *c) {           /* (MediaData *) */
    Ext *e = ext_of(A0);
    MD *m = md_of(A1);
    if (!e || !m) { RET(ST_INVALID); return; }
    ext_lock(e);
    md_clear(m);
    if (e->have_pending) { md_set_i64(m, "timeUs", e->pend_us); md_set_i32(m, "track-index", e->pend_track); md_set_i32(m, "is-sync-frame", 1); }
    ext_unlock(e);
    RET(ST_OK);
}

static void ext_GetBufferedRange(Ctx *c) {            /* (int64 *startUs, int64 *endUs) */
    Ext *e = ext_of(A0);
    if (!e) { RET(ST_INVALID); return; }
    if (A1) wr64(A1, 0);
    if (A2) wr64(A2, (uint64_t)e->duration_us);
    RET(ST_OK);
}

/* ---------------------------------------------------------------- Decoder virtual functions */
static void dec_lock(Dec *d) { EnterCriticalSection(&d->cs); }
static void dec_unlock(Dec *d) { LeaveCriticalSection(&d->cs); }
/* Takes the lock of a decoder that is still alive; returns 0 (not locked) when the destructor already ran on another
 * thread, and the caller answers ST_INVALID. dec_live is the check for the methods that only read fields of the
 * structure, which is never freed (see g_dec_live). */
static int dec_enter(Dec *d) { EnterCriticalSection(&d->cs); if (!d->dead) return 1; LeaveCriticalSection(&d->cs); return 0; }
static int dec_live(const Dec *d) { return d && !d->dead; }

static char g_mlog[4096][192]; static volatile LONG g_mlog_n, g_mlog_started;
static DWORD WINAPI mlog_thread(void *p) {            /* SSBU_MOVIE_LOG=2: the lines kept in memory, every 2 s (older than 4096 back: lost) */
    (void)p;
    LONG done = 0;
    for (;;) {
        Sleep(2000);
        LONG n = g_mlog_n;
        if (n - done > 4096) { printf("movie: (log: %ld lines lost)\n", (long)(n - done - 4096)); done = n - 4096; }
        for (; done < n; done++) fputs(g_mlog[done & 4095], stdout);
        fflush(stdout);
    }
    return 0;
}
static void dlog(Dec *d, const char *fmt, ...) {      /* SSBU_MOVIE_LOG: one line per call, with thread and time */
    if (!g_log) return;
    char line[256];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(line, sizeof line, fmt, ap);
    va_end(ap);
    if (g_log == 2) {                                 /* SSBU_MOVIE_LOG=2: into memory, written out by mlog_thread every 2 s (less timing change) */
        LONG k = InterlockedIncrement(&g_mlog_n) - 1;
        snprintf(g_mlog[k & 4095], sizeof g_mlog[0], "movie[%5lu %8llu] %c %s\n", GetCurrentThreadId(), (unsigned long long)GetTickCount64(), d->is_video ? 'V' : 'A', line);
        if (!InterlockedExchange(&g_mlog_started, 1)) CloseHandle(CreateThread(NULL, 0, mlog_thread, NULL, 0, NULL));
        return;
    }
    printf("movie[%5lu %8llu] %c %s\n", GetCurrentThreadId(), (unsigned long long)GetTickCount64(), d->is_video ? 'V' : 'A', line);
}

/* Frees every sample the decoder holds and empties all lists (caller holds the lock). */
static int h264_pump(Dec *d);
static void dec_release_all(Dec *d) {
    for (int i = 0; i < d->nout; i++) { if (d->out[i].s) IMFSample_Release(d->out[i].s); memset(&d->out[i], 0, sizeof d->out[i]); }
    for (int i = 0; i < d->nin; i++) {
        if (d->in_state[i] == IN_DECODING && d->in_data[i].s) IMFSample_Release(d->in_data[i].s);
        if (!d->h264 && d->mem) {                     /* sample tokens exist on the WebM path only */
            Token t;                                  /* a sample read into the buffer but not sent yet */
            memcpy(&t, d->mem + (size_t)i * d->slot, sizeof t);
            if (t.magic == TOKEN_MAGIC && t.s) IMFSample_Release(t.s);
            memset(d->mem + (size_t)i * d->slot, 0, d->slot);
        }
        memset(&d->in_data[i], 0, sizeof d->in_data[i]);
        d->in_state[i] = IN_CODEC;
    }
    d->in_n = d->dec_n = d->out_n = 0;
    d->eos_in = 0;                                    /* (WebM too: after Flush / Stop the stream may be fed again) */
    if (d->h264) {                                    /* decoded but not handed out, and what the transform holds */
        for (int i = 0; i < d->pend_n; i++) if (d->pend[i].s) IMFSample_Release(d->pend[i].s);
        d->pend_n = 0;
        if (d->mft) IMFTransform_ProcessMessage(d->mft, MFT_MESSAGE_COMMAND_FLUSH, 0);
        d->csd_sent = 0;                              /* after a flush (a seek) the decoder needs the parameter sets again */
        d->eos_in = 0; d->parked_n = 0;               /* Start offers every input buffer again */
    }
}

/* The codec's own progress (caller holds the lock): every input waiting in decode moves to a free output buffer,
 * and its input buffer is offered again. Returns bit 0 = input indices were offered, bit 1 = frames became ready. */
static int dec_pump(Dec *d) {
    if (d->h264) return h264_pump(d);
    int ev = 0;
    while (d->dec_n > 0) {
        int o = -1;
        for (int i = 0; i < d->nout; i++) if (d->out[i].state == OUT_FREE) { o = i; break; }
        if (o < 0) break;
        int in = d->dec_list[0];
        memmove(d->dec_list, d->dec_list + 1, (size_t)(d->dec_n - 1) * sizeof d->dec_list[0]);
        d->dec_n--;
        d->out[o].s = d->in_data[in].s; d->out[o].ts = d->in_data[in].ts; d->out[o].flags = d->in_data[in].flags;
        d->out[o].state = OUT_READY;
        d->out_list[d->out_n++] = o;
        memset(&d->in_data[in], 0, sizeof d->in_data[in]);
        if (d->eos_in) { d->in_state[in] = IN_CODEC; ev |= 2; continue; }      /* after the end of stream: not offered again */
        d->in_state[in] = IN_OFFERED;
        d->in_list[d->in_n++] = in;
        ev |= 3;
    }
    return ev;
}
static void dec_signal(Dec *d, int ev) { if (ev & 2) signal_event(d, 1); if (ev & 1) signal_event(d, 0); }

/* ---------------------------------------------------------------- H.264 elementary streams (Media Foundation transform)
 * Every call below runs with the decoder locked. h264_open picks the first synchronous H.264 decoder transform Windows
 * registers (Microsoft's software decoder; asynchronous hardware transforms need an event loop and are left out).
 * Known cost, left for later: ProcessInput / ProcessOutput run under d->cs on the game's feed thread, and every
 * ProcessOutput attempt gets a new output buffer of one picture (about 1.4 MB at 720p) when the transform does not
 * provide its own. */
static int h264_sps_dims(const uint8_t *sps, size_t len, int *width, int *height, double *fps);
static UINT32 h264_enum(IMFActivate ***act) {         /* the transforms h264_open may use */
    MFT_REGISTER_TYPE_INFO in = {MFMediaType_Video, MFVideoFormat_H264};
    UINT32 n = 0;
    *act = NULL;
#ifdef MOVIE_FFMPEG
    if (!ffmf_forced())
#endif
    if (!movie_mf_present() || FAILED(MFTEnumEx(MFT_CATEGORY_VIDEO_DECODER, MFT_ENUM_FLAG_SYNCMFT | MFT_ENUM_FLAG_LOCALMFT | MFT_ENUM_FLAG_SORTANDFILTER, &in, NULL, act, &n))) n = 0;
#ifdef MOVIE_FFMPEG
    if (!n && ffmf_allowed()) {                       /* none (Windows N, or SSBU_MOVIE_FFMPEG=1): FFmpeg's */
        CoTaskMemFree(*act); *act = NULL;
        if (FAILED(ffmf_MFTEnumEx(MFT_CATEGORY_VIDEO_DECODER, MFT_ENUM_FLAG_SYNCMFT, &in, NULL, act, &n))) n = 0;
    }
#endif
    return n;
}
/* Whether this PC has an H.264 decoder transform at all (asked once). Without one, CreateH264DecoderConfigurationData
 * answers "unsupported" as it did before the H.264 path existed, and the game handles it the way it did then. */
static int h264_available(void) {
    static volatile LONG known = -1;
    if (known < 0) {
        com_init();
        IMFActivate **act = NULL;
        UINT32 n = h264_enum(&act);
        for (UINT32 i = 0; i < n; i++) IMFActivate_Release(act[i]);
        CoTaskMemFree(act);
        if (!n) printf("movie: no H.264 decoder transform on this PC: final smash movies stay unsupported\n");
        InterlockedExchange(&known, n ? 1 : 0);
    }
    return known > 0;
}
static int h264_set_output(Dec *d) {
    IMFMediaType *t = NULL;
    for (DWORD k = 0; SUCCEEDED(IMFTransform_GetOutputAvailableType(d->mft, 0, k, &t)); k++) {
        GUID sub;
        if (SUCCEEDED(IMFMediaType_GetGUID(t, &MF_MT_SUBTYPE, &sub)) && IsEqualGUID(&sub, &MFVideoFormat_NV12)) {
            HRESULT hr = IMFTransform_SetOutputType(d->mft, 0, t, 0);
            UINT64 fs = 0;
            if (SUCCEEDED(hr) && SUCCEEDED(IMFMediaType_GetUINT64(t, &MF_MT_FRAME_SIZE, &fs))) {
                int fw = (int)(fs >> 32), fh = (int)(fs & 0xffffffff);
                d->plane_h = fh;                      /* the luma plane's rows: 1088 for a 1080-line picture */
                if (d->w <= 0 || d->h <= 0) { d->w = fw; d->h = fh; }
            }
            IMFMediaType_Release(t);
            MFT_OUTPUT_STREAM_INFO si;
            if (SUCCEEDED(hr) && SUCCEEDED(IMFTransform_GetOutputStreamInfo(d->mft, 0, &si))) {
                d->mft_provides = (si.dwFlags & (MFT_OUTPUT_STREAM_PROVIDES_SAMPLES | MFT_OUTPUT_STREAM_CAN_PROVIDE_SAMPLES)) != 0;
                d->mft_out_size = si.cbSize;
            }
            return SUCCEEDED(hr);
        }
        IMFMediaType_Release(t);
    }
    return 0;
}
static int h264_open(Dec *d) {
    IMFActivate **act = NULL;
    UINT32 n = h264_enum(&act);
    for (UINT32 i = 0; i < n; i++) {
        if (!d->mft && SUCCEEDED(IMFActivate_ActivateObject(act[i], &IID_IMFTransform, (void **)&d->mft))) {
            WCHAR name[128] = L"?";
            IMFActivate_GetString(act[i], &MFT_FRIENDLY_NAME_Attribute, name, 128, NULL);
            printf("movie: H.264 decoder: %ls\n", name);
        }
        IMFActivate_Release(act[i]);
    }
    CoTaskMemFree(act);
    if (!d->mft) { printf("movie: no H.264 decoder transform (%u found, none could be created)\n", n); return 0; }
    IMFMediaType *t = NULL;
    HRESULT hr = new_media_type(d->mft, &t);
    if (SUCCEEDED(hr)) {
        IMFMediaType_SetGUID(t, &MF_MT_MAJOR_TYPE, &MFMediaType_Video);
        IMFMediaType_SetGUID(t, &MF_MT_SUBTYPE, &MFVideoFormat_H264);
        IMFMediaType_SetUINT32(t, &MF_MT_INTERLACE_MODE, MFVideoInterlace_Progressive);
        if (d->w > 0 && d->h > 0) IMFMediaType_SetUINT64(t, &MF_MT_FRAME_SIZE, ((UINT64)(UINT32)d->w << 32) | (UINT32)d->h);
        hr = IMFTransform_SetInputType(d->mft, 0, t, 0);
        IMFMediaType_Release(t);
    }
    if (FAILED(hr) || !h264_set_output(d)) {
        printf("movie: H.264 decoder refused the stream (input type %08lx)\n", hr);
        IMFTransform_Release(d->mft); d->mft = NULL;
        return 0;
    }
    IMFTransform_ProcessMessage(d->mft, MFT_MESSAGE_NOTIFY_BEGIN_STREAMING, 0);
    IMFTransform_ProcessMessage(d->mft, MFT_MESSAGE_NOTIFY_START_OF_STREAM, 0);
    return 1;
}
/* Takes every frame the transform has ready into pend[]. */
static void h264_collect(Dec *d) {
    for (int guard = 0; guard < 4 * MAX_OUT; guard++) {
        MFT_OUTPUT_DATA_BUFFER ob;
        memset(&ob, 0, sizeof ob);
        DWORD status = 0;
        if (!d->mft_provides) {
            IMFMediaBuffer *mb = NULL;
            DWORD size = d->mft_out_size ? d->mft_out_size : (DWORD)((d->w + 32) * (d->plane_h > d->h ? d->plane_h : d->h) * 2);
            if (FAILED(new_buffer(d->mft, size, &mb))) return;
            if (FAILED(new_sample(d->mft, &ob.pSample))) { IMFMediaBuffer_Release(mb); return; }
            IMFSample_AddBuffer(ob.pSample, mb);
            IMFMediaBuffer_Release(mb);
        }
        HRESULT hr = IMFTransform_ProcessOutput(d->mft, 0, 1, &ob, &status);
        if (ob.pEvents) IMFCollection_Release(ob.pEvents);
        if (hr == MF_E_TRANSFORM_STREAM_CHANGE) {
            if (ob.pSample) IMFSample_Release(ob.pSample);
            if (!h264_set_output(d)) return;
            continue;
        }
        if (FAILED(hr) || !ob.pSample) {
            if (ob.pSample) IMFSample_Release(ob.pSample);
            if (FAILED(hr) && hr != MF_E_TRANSFORM_NEED_MORE_INPUT && !d->warned_h264) { d->warned_h264 = 1; printf("movie: H.264 decoder output failed: %08lx\n", hr); }
            return;
        }
        LONGLONG t = 0;
        IMFSample_GetSampleTime(ob.pSample, &t);
        if (d->pend_n < MAX_OUT) {
            d->pend[d->pend_n].s = ob.pSample; d->pend[d->pend_n].ts = t / 10; d->pend[d->pend_n].flags = 0;
            d->pend_n++;
        } else { IMFSample_Release(ob.pSample); d->dropped++; }
    }
}
/* Back-pressure, as the WebM path has it (an input is decoded only into a free output buffer): an input buffer goes back
 * to the game only while few decoded frames wait for an output buffer. Without it the game pushes a whole final smash
 * movie in at once, the transform decodes it faster than the game shows it, and frames were thrown away (2026-10-15:
 * about 70 of 196 shown, and the feed thread spun on end-of-stream buffers at 8-10 ms of CPU per frame). */
#define H264_PEND_LIMIT 4
/* Decoded frames into free output buffers, then held-back input buffers back to the game; returns 2 when frames became
 * ready, | 1 when input buffers were offered. */
static int h264_pump(Dec *d) {
    int ev = 0;
    while (d->pend_n > 0) {
        int o = -1;
        for (int i = 0; i < d->nout; i++) if (d->out[i].state == OUT_FREE) { o = i; break; }
        if (o < 0) break;
        d->out[o].s = d->pend[0].s; d->out[o].ts = d->pend[0].ts; d->out[o].flags = d->pend[0].flags;
        d->out[o].state = OUT_READY;
        d->out_list[d->out_n++] = o;
        memmove(d->pend, d->pend + 1, (size_t)(d->pend_n - 1) * sizeof d->pend[0]);
        d->pend_n--;
        ev |= 2;
    }
    while (!d->eos_in && d->pend_n < H264_PEND_LIMIT && d->parked_n > 0) {
        int i = d->parked[--d->parked_n];
        d->in_state[i] = IN_OFFERED;
        d->in_list[d->in_n++] = i;
        ev |= 1;
    }
    return ev;
}
/* The game wrote `size` bytes of NAL units at `off` of input buffer i: decode them, give the buffer back. */
static int h264_send(Dec *d, int i, int off, int size, int64_t ts, uint32_t flags) {
    if (off < 0 || size < 0 || (size_t)off + (size_t)size > d->slot) { off = 0; size = 0; }
    const unsigned char *data = d->mem + (size_t)i * d->slot + off;
    if (d->save && size > 0) fwrite(data, 1, (size_t)size, d->save);
    if (d->in_count == 1 && size > 0) {
        printf("movie: Decoder(video): first H.264 input: %d bytes at t=%.3f s, starts", size, ts / 1e6);
        for (int k = 0; k < size && k < 8; k++) printf(" %02x", data[k]);
        printf("\n");
    }
    if (size > 0 && d->mft) {
        /* the decoder reads Annex B: a unit handed over without its start code gets one */
        int sc = !(size >= 3 && data[0] == 0 && data[1] == 0 && (data[2] == 1 || (size >= 4 && data[2] == 0 && data[3] == 1)));
        size_t pre = d->csd_sent ? 0 : d->csd_len, total = pre + (sc ? 4 : 0) + (size_t)size;
        IMFMediaBuffer *mb = NULL;
        IMFSample *s = NULL;
        BYTE *p = NULL;
        if (SUCCEEDED(new_buffer(d->mft, (DWORD)total, &mb)) && SUCCEEDED(IMFMediaBuffer_Lock(mb, &p, NULL, NULL))) {
            if (pre) memcpy(p, d->csd, pre);
            if (sc) { static const unsigned char code[4] = {0, 0, 0, 1}; memcpy(p + pre, code, 4); pre += 4; }
            memcpy(p + pre, data, (size_t)size);
            IMFMediaBuffer_Unlock(mb);
            IMFMediaBuffer_SetCurrentLength(mb, (DWORD)total);
            if (SUCCEEDED(new_sample(d->mft, &s))) {
                IMFSample_AddBuffer(s, mb);
                IMFSample_SetSampleTime(s, ts * 10);
                HRESULT hr = IMFTransform_ProcessInput(d->mft, 0, s, 0);
                if (hr == MF_E_NOTACCEPTING) { h264_collect(d); hr = IMFTransform_ProcessInput(d->mft, 0, s, 0); }
                if (SUCCEEDED(hr)) d->csd_sent = 1;
                else if (!d->warned_h264) { d->warned_h264 = 1; printf("movie: H.264 decoder input failed: %08lx\n", hr); }
                IMFSample_Release(s);
            }
        }
        if (mb) IMFMediaBuffer_Release(mb);
        h264_collect(d);
    }
    if (ts > d->last_ts) d->last_ts = ts;
    if ((flags & FLAG_EOS) && !d->eos_in) {           /* the rest of the pictures, then one end-of-stream buffer */
        d->eos_in = 1;
        if (d->mft) { IMFTransform_ProcessMessage(d->mft, MFT_MESSAGE_COMMAND_DRAIN, 0); h264_collect(d); }
        if (d->pend_n < MAX_OUT) { d->pend[d->pend_n].s = NULL; d->pend[d->pend_n].ts = d->last_ts; d->pend[d->pend_n].flags = FLAG_EOS; d->pend_n++; }
        else printf("movie: Decoder(video): WARNING no room for the H.264 end of stream (%d frames waiting)\n", d->pend_n);
        printf("movie: Decoder(video): H.264 end of stream after %llu inputs\n", d->in_count);
    }
    if (d->eos_in) d->in_state[i] = IN_CODEC;         /* nothing more to feed: the game's feed thread waits instead of sending end of stream again */
    else if (d->pend_n >= H264_PEND_LIMIT) { d->in_state[i] = IN_CODEC; d->parked[d->parked_n++] = i; }
    else { d->in_state[i] = IN_OFFERED; d->in_list[d->in_n++] = i; }    /* the data was copied: the buffer can be filled again */
    return h264_pump(d) | (d->in_state[i] == IN_OFFERED ? 1 : 0);
}
static void h264_close(Dec *d) {
    for (int i = 0; i < d->pend_n; i++) if (d->pend[i].s) IMFSample_Release(d->pend[i].s);
    d->pend_n = 0;
    if (d->mft) { IMFTransform_ProcessMessage(d->mft, MFT_MESSAGE_NOTIFY_END_STREAMING, 0); IMFTransform_Release(d->mft); d->mft = NULL; }
    if (d->save) { fclose(d->save); d->save = NULL; }
    free(d->csd); d->csd = NULL; d->csd_len = 0;
}

static void dec_dtor_common(Ctx *c, int deleting) {
    Dec *d = dec_of(A0);
    if (d) {
        /* Unlisted first (from here on dec_of finds nothing for this object), then emptied and marked dead under the
         * lock; the structure and its critical section are kept so a method already running on another thread finds
         * d->dead after dec_enter instead of touching freed memory (see g_dec_live). */
        dec_listed(d, 0);
        if (d->h264) com_init();                      /* the transform is released below */
        dec_lock(d);
        if (!d->dead) {
            dec_release_all(d);
            h264_close(d);
            printf("movie: Decoder(%s) destroyed: %llu input buffers, %llu output buffers, %llu copied to the game, %llu refused, %llu flushes\n",
                   d->is_video ? "video" : "audio", d->in_count, d->out_count, d->copied, d->dropped, d->flushes);
            if (d->h264) free(InterlockedExchangePointer((void *volatile *)&g_h264_mem_grace, d->mem));   /* the previous one's */
            else free(d->mem);
            d->mem = NULL; d->nin = d->nout = 0;
            d->in_n = d->dec_n = d->out_n = 0;
            d->dead = 1;
        }
        dec_unlock(d);
        wr64(A0 + 8, 0);
    }
    if (deleting) gcall(c, GAME_FREE, A0, 0, 0, 0, 0);       /* the game allocated the 16-byte object with f_710392dce0 [game 0x71036f1ccc] */
}
static void dec_dtor(Ctx *c) { dec_dtor_common(c, 0); }
static void dec_deleting_dtor(Ctx *c) { dec_dtor_common(c, 1); }

static void dec_Configure(Ctx *c) {                   /* (MediaData *format) */
    Dec *d = dec_of(A0);
    MD *m = md_of(A1);
    if (!d || !dec_enter(d)) { RET(ST_INVALID); return; }
    uint64_t ext = 0; int32_t track = -1, v = 0;
    const char *mime = "?";
    if (m) {
        md_get_ptr(m, "nn-extractor", &ext);
        md_get_i32(m, "nn-track", &track);
        md_get_str(m, "mime", &mime);
        if (md_get_i32(m, "width", &v)) d->w = v;
        if (md_get_i32(m, "height", &v)) d->h = v;
        if (md_get_i32(m, "sample-rate", &v)) d->rate = v;
        if (md_get_i32(m, "channel-count", &v)) d->ch = v;
    }
    d->ext = (Ext *)(uintptr_t)ext;
    d->track = track;
    dec_unlock(d);
    printf("movie: Decoder(%s type %d, output format %d) configured for track %d (%s%s, %dx%d, %d Hz, %d ch)\n",
           d->is_video ? "video" : "audio", d->type, d->fmt, track, mime, ext ? "" : ", NO extractor link, ", d->w, d->h, d->rate, d->ch);
    if (!ext && d->type == 1) {                       /* H.264 the game feeds itself (CreateH264DecoderConfigurationData made the format) */
        const unsigned char *csd = NULL; size_t csd_len = 0; int64_t max_in = 0;
        if (m) md_get_buf(m, "nn-h264-csd", &csd, &csd_len);
        if (m) { int32_t mi = 0; if (md_get_i32(m, "max-input-size", &mi)) max_in = mi; else md_get_i64(m, "max-input-size", &max_in); }
        com_init();
        if (!dec_enter(d)) { RET(ST_INVALID); return; }
        int ok = 0;
        if (!d->mft) {
            free(d->csd); d->csd = NULL; d->csd_len = 0;      /* a second Configure replaces the first copy */
            if (csd && csd_len > 0) {
                d->csd = malloc(csd_len);
                if (d->csd) { memcpy(d->csd, csd, csd_len); d->csd_len = csd_len; }
                else printf("movie: Decoder(video): no memory for the %zu bytes of H.264 parameter sets\n", csd_len);
            }
            if (d->csd_len && (d->w <= 0 || d->h <= 0)) {     /* the size from the SPS (after its start code and header byte) */
                int w = 0, h = 0; double fps = 0;
                if (d->csd_len > 5 && h264_sps_dims(d->csd + 4, d->csd_len - 4, &w, &h, &fps)) { d->w = w; d->h = h; }
            }
            size_t slot = (size_t)(max_in > 0 ? max_in : 0) + 0x5000;
            if (slot < (2u << 20)) slot = 2u << 20;   /* a 1080p key frame fits; the game copies whole NAL units into the buffer */
            unsigned char *mem = calloc((size_t)d->nin, slot);
            if (mem) { free(d->mem); d->mem = mem; d->slot = slot; d->h264 = 1; }
            else printf("movie: Decoder(video): no memory for %d H.264 input buffers of %zu KB\n", d->nin, slot >> 10);
            const char *save = getenv("SSBU_MOVIE_SAVE_H264");
            if (save && save[0] && !d->save) d->save = fopen(save, "wb");
            ok = mem && h264_open(d);
        } else ok = 1;
        dec_unlock(d);
        printf("movie: Decoder(video): H.264 elementary stream %s (%dx%d, parameter sets %zu bytes, input buffers %zu KB)\n",
               ok ? "ready" : "NOT decodable", d->w, d->h, d->csd_len, d->slot >> 10);
        RET(ok ? ST_OK : ST_UNSUPPORTED);
        return;
    }
    if (!ext) { RET(ST_UNSUPPORTED); return; }
    RET(ST_OK);                                       /* input buffers are offered by Start, not here */
}

static void dec_RegisterClientEvents(Ctx *c) {
    Dec *d = dec_of(A0);
    if (!d || !dec_enter(d)) { RET(ST_INVALID); return; }
    d->events = A1;
    int ev = (d->in_n > 0 ? 1 : 0) | (d->out_n > 0 ? 2 : 0);     /* registered after Start: nothing may be lost */
    dec_unlock(d);
    dec_signal(d, ev);
    RET(ST_OK);
}

static void dec_fill_format(Dec *d, MD *m) {
    md_clear(m);
    if (d->is_video) {
        int w = d->w, h = d->h;
        md_set_str(m, "mime", "video/raw");
        md_set_i32(m, "width", w); md_set_i32(m, "height", h);
        md_set_i32(m, "stride", w); md_set_i32(m, "slice-height", h);
        md_set_i32(m, "crop-width", w); md_set_i32(m, "crop-height", h);
        md_set_i32(m, "color-format", 21);            /* OMX_COLOR_FormatYUV420SemiPlanar = NV12 */
        md_set_i32(m, "nv12-width", w); md_set_i32(m, "nv12-height", h);
        md_set_i32(m, "nv12-y-stride", w); md_set_i32(m, "nv12-uv-stride", w);
        md_set_i32(m, "nv12-y-offset", 0); md_set_i32(m, "nv12-uv-offset", w * h);
        md_set_i32(m, "nv12-colorspace", 0);
    } else {
        md_set_str(m, "mime", "audio/raw");
        md_set_i32(m, "sample-rate", d->rate); md_set_i32(m, "channel-count", d->ch);
        md_set_i32(m, "pcm-encoding", 2);             /* 16-bit */
    }
}

static void dec_GetOutputFormat(Ctx *c) { Dec *d = dec_of(A0); MD *m = md_of(A1); if (!dec_live(d) || !m) { RET(ST_INVALID); return; } dec_fill_format(d, m); RET(ST_OK); }
static void dec_GetOutputBufferFormat(Ctx *c) { Dec *d = dec_of(A0); MD *m = md_of(A2); if (!dec_live(d) || !m) { RET(ST_INVALID); return; } dec_fill_format(d, m); RET(ST_OK); }

/* P3 round 3: which decoders send the "output format" event (DecoderEvents + 0x10). The game's handler thread
 * [game 0x71036f3500] signals the player's "formats known" event (player + 0x498) only when the format event of EVERY
 * decoder it created has arrived (cases 3 and 7 of its switch: flags + 0x4c1 and + 0x4c0), and the playback thread
 * waits for it for 5 s while holding the player's mutex [0x71036f2580]: with the event sent by the video decoder only,
 * every movie start waited the full 5 s and the main thread stood at that mutex [0x71036e7690]. So the real audio
 * decoder sends it as well. SSBU_MOVIE_NO_AUDIO_FORMAT_EVENT=1: video only, as before. */
static int fmt_event_wanted(const Dec *d) {
    static int video_only = -1;
    if (video_only < 0) video_only = getenv("SSBU_MOVIE_NO_AUDIO_FORMAT_EVENT") != NULL;
    return (d->is_video || !video_only) && !d->fmt_signalled;
}
static void dec_Start(Ctx *c) {
    Dec *d = dec_of(A0);
    {   /* TEST ONLY, SSBU_MOVIE_TEST_START_DELAY=<ms>: the first Start of each decoder waits that long (a slow movie start: the
         * player stays prepared, state 3, long enough for an early resync seek to run before the audio output's Init) */
        static int delay = -1;
        if (delay < 0) { const char *v = getenv("SSBU_MOVIE_TEST_START_DELAY"); delay = v ? atoi(v) : 0; }
        if (delay > 0 && d && !d->started && !d->flushes) { printf("movie: TEST: first Start held %d ms\n", delay); Sleep((DWORD)delay); }
    }
    if (!d || !dec_enter(d)) { RET(ST_INVALID); return; }
    int offer = !d->started || d->flushed;            /* first start, or the start that follows a flush: all input buffers are offered */
    if (offer) {
        dec_release_all(d);
        for (int i = 0; i < d->nin; i++) { d->in_state[i] = IN_OFFERED; d->in_list[i] = i; }
        d->in_n = d->nin;
    }
    d->started = 1; d->flushed = 0;
    int fmt = fmt_event_wanted(d);
    if (fmt) d->fmt_signalled = 1;
    dec_unlock(d);
    dlog(d, "Start%s", offer ? " (all input buffers offered)" : " (already running)");
    if (fmt) signal_event(d, 2);
    if (offer) signal_event(d, 0);
    RET(ST_OK);
}
static void dec_halt(Ctx *c, const char *what, int stop) {
    Dec *d = dec_of(A0);
    if (!d || !dec_enter(d)) { RET(ST_INVALID); return; }
    int held_in = 0, held_out = 0;
    for (int i = 0; i < d->nin; i++) held_in += d->in_state[i] == IN_CLIENT;
    for (int i = 0; i < d->nout; i++) held_out += d->out[i].state == OUT_CLIENT;
    int queued = d->out_n + d->dec_n;
    dec_release_all(d);
    d->flushed = 1; d->flushes++;
    if (stop) d->started = 0;
    dec_unlock(d);
    dlog(d, "%s: dropped %d decoded frames, voided %d input and %d output indices held by the game", what, queued, held_in, held_out);
    RET(ST_OK);                                       /* no event: nothing is offered until Start */
}
static void dec_Stop(Ctx *c) { dec_halt(c, "Stop", 1); }
static void dec_Flush(Ctx *c) { dec_halt(c, "Flush", 0); }
static void dec_Reset(Ctx *c) { dec_halt(c, "Reset", 1); }
/* [subsdk 0x21090] Decoder::GetLastError: 0x1000 without an implementation object, else DecoderImpl +0xd8 [0x1fc80]. That field is
 * written by the codec's message receiver [0x203a8..0x20410]: on an error message the status (0x1000 unless the codec's own code
 * converts to another one [0x35e140]) is stored and the client's error event (+0x18) is signalled [0x20428]. Here the codec is Media
 * Foundation's, inside the source reader: a failed read of the track is that error; its HRESULT has no movie::Status, so 0x1000. */
static void dec_error_check(Dec *d) {                 /* called with the decoder locked */
    if (d->last_error || !d->ext || d->track < 0 || d->track >= d->ext->ntracks || !d->ext->tr[d->track].failed) return;
    d->last_error = ST_FAILED;
    printf("movie: decoder of track %d: codec error -> last error 0x%x, error event signalled\n", d->track, ST_FAILED);
    signal_event(d, 3);
}
static void dec_GetLastError(Ctx *c) { Dec *d = dec_of(A0); RET(dec_live(d) ? d->last_error : ST_FAILED); }   /* destroyed = no implementation */

static void dec_AcquireInputBufferIndex(Ctx *c) {     /* (int *index, int *moreAvailable) */
    Dec *d = dec_of(A0);
    if (!d || !A1 || !A2) { RET(ST_INVALID); return; }     /* both pointers are required [subsdk 0x1fa48] */
    if (!dec_enter(d)) { RET(ST_INVALID); return; }
    int found = -1, more = 0;
    if (d->in_n > 0) {
        found = d->in_list[0];
        memmove(d->in_list, d->in_list + 1, (size_t)(d->in_n - 1) * sizeof d->in_list[0]);
        more = --d->in_n;
        d->in_state[found] = IN_CLIENT;
        d->client_since[found] = GetTickCount64();
    }
    dec_unlock(d);
    wr32(A1, (uint32_t)found);
    wr32(A2, (uint32_t)more);
    dlog(d, "AcquireInput -> %d (more %d)", found, more);
    RET(found >= 0 ? ST_OK : ST_NO_INPUT);
}

static void dec_GetInputBuffer(Ctx *c) {              /* (int index, Buffer *out) */
    Dec *d = dec_of(A0);
    int i = (int)A1;
    uint64_t b = A2;
    if (!d || !b || i < 0 || i >= d->nin) { RET(ST_INVALID); return; }
    /* d->mem and d->slot are read under the lock (Configure swaps in the H.264 buffers, the destructor frees them); the
     * game's Buffer is released after it, since that may call the game's free */
    if (!dec_enter(d)) { RET(ST_INVALID); return; }
    int ok = d->mem && i < d->nin;
    uint64_t base = ok ? (uint64_t)(uintptr_t)(d->mem + (size_t)i * d->slot) : 0, cap = ok ? (uint64_t)d->slot : 0;
    if (ok && !d->h264) d->feeder_tid = GetCurrentThreadId();   /* the feed thread of this track (feeder_found_empty) */
    dec_unlock(d);
    t_gti_fed = 1;
    if (!ok) { RET(ST_INVALID); return; }
    buf_release(c, b);
    wr64(b + B_BASE, base);
    wr64(b + B_CAP, cap);
    wr32(b + B_OFFSET, 0); wr32(b + B_SIZE, 0);
    RET(ST_OK);
}

static void dec_SendInputBufferForDecode(Ctx *c) {    /* (int index, int offset, int size, int64 timeUs, unsigned flags) */
    Dec *d = dec_of(A0);
    int i = (int)A1, size = (int)A3;                  /* A2 = offset, A3 = size, A4 = timeUs, x5 = flags [game 0x71036f6e2c] */
    int64_t ts = (int64_t)A4;
    uint32_t flags = (uint32_t)c->x[5];
    if (!d || i < 0 || i >= d->nin) { RET(ST_INVALID); return; }
    if (d->h264) {                                    /* compressed data the game wrote itself */
        com_init();
        if (!dec_enter(d)) { RET(ST_INVALID); return; }
        int held = i < d->nin && d->in_state[i] == IN_CLIENT, ev = 0;
        if (held) { d->in_count++; ev = h264_send(d, i, (int)A2, size, ts, flags); }
        else d->dropped++;
        dec_unlock(d);
        dlog(d, "SendInput H.264 %d: %d bytes t=%.3f flags %x%s", i, size, ts / 1e6, flags, held ? "" : " REFUSED (index not held by the game)");
        dec_signal(d, ev);
        RET(held ? ST_OK : ST_INVALID);
        return;
    }
    int test_held = 0;
    {   /* TEST ONLY, SSBU_MOVIE_TEST_VIDEO_DELAY=<ms>: the first video sample of each decoder is held that long before it is
         * taken (a slow first VP9 picture, as on a busy PC: the boot resync then comes before the first video frame) */
        static int delay = -1;
        if (delay < 0) { const char *v = getenv("SSBU_MOVIE_TEST_VIDEO_DELAY"); delay = v ? atoi(v) : 0; }
        if (delay > 0 && d->is_video && d->in_count == 0 && !(flags & FLAG_EOS)) { printf("movie: TEST: first video sample held %d ms\n", delay); Sleep((DWORD)delay); test_held = 1; }
    }
    if (!dec_enter(d)) { RET(ST_INVALID); return; }   /* d->mem is gone once the destructor ran */
    dec_error_check(d);
    IMFSample *sample = NULL;
    int stale = 0;
    Token t;
    memcpy(&t, d->mem + (size_t)i * d->slot, sizeof t);
    memset(d->mem + (size_t)i * d->slot, 0, sizeof t);
    if (t.magic == TOKEN_MAGIC && t.s) {
        sample = t.s;
        if (ts <= 0) ts = t.ts;
        if (d->ext && t.gen != d->ext->gen) stale = 1;      /* read before the last SeekTo */
    } else if (!(flags & FLAG_EOS) && !d->warned_token) {
        d->warned_token = 1;
        printf("movie: Decoder(%s): input buffer %d holds no sample token (size %d): dropped\n", d->is_video ? "video" : "audio", i, size);
    }
    if (d->in_state[i] != IN_CLIENT || stale) {       /* an index voided by Flush, or data from before the seek: the codec refuses it */
        if (sample) IMFSample_Release(sample);
        d->dropped++;
        int was = d->in_state[i];
        int ev = 0;
        if (was == IN_CLIENT) { d->in_state[i] = IN_OFFERED; d->in_list[d->in_n++] = i; ev = 1; }
        dec_unlock(d);
        dlog(d, "SendInput %d REFUSED (%s) t=%.3f flags %x", i, was != IN_CLIENT ? "index not held by the game" : "sample from before the seek", ts / 1e6, flags);
        dec_signal(d, ev);
        RET(was == IN_CLIENT ? ST_OK : ST_INVALID);
        return;
    }
    d->in_count++;
    if (g_test_resync_at && d->is_video && d->in_count == (unsigned long long)g_test_resync_at) {
        /* SSBU_MOVIE_TEST_RESYNC=<flag>,<n>: at the n-th video sample raise the game's own "re-synchronise movies" request
         * (byte 0x7107446040, set by its system-notification handler f_7103741700: 8 = operation mode changed, 4 / 2 = the
         * two halves of a focus change); the movie manager [game 0x71036e3984] then pauses, seeks and resumes the player. */
        /* Read in the game [0x71036e3988..0x71036e3a7c]: 4 = PAUSE the playing movie (focus lost; nothing else), 2 = resume:
         * re-sync state 1 / 4 frames -> seek + start (focus back), 8 = re-sync state 1 or 5 / 30 frames. So 4 alone keeps the
         * movie paused for good, as on the console with the HOME menu open: SSBU_MOVIE_TEST_RESYNC=4,<n>,<flag2>,<ms> raises
         * <flag2> (2 = focus back) <ms> later from a thread of its own. */
        uint8_t *req = (uint8_t *)(uintptr_t)GA(0x7107446040ULL);
        InterlockedOr8((char *)req, (char)g_test_resync_flag);
        printf("movie: TEST: resync request %d raised at video sample %d\n", g_test_resync_flag, g_test_resync_at);
        if (g_test_resync_flag2) CloseHandle(CreateThread(NULL, 0, test_resync_later, req, 0, NULL));
    }
    if (!sample && !(flags & FLAG_EOS)) {             /* nothing to decode: the buffer is offered again */
        d->dropped++;
        d->in_state[i] = IN_OFFERED; d->in_list[d->in_n++] = i;
        dec_unlock(d);
        signal_event(d, 0);
        /* TEST ONLY (V 22/10), with SSBU_MOVIE_TEST_VIDEO_DELAY: a seek's Flush + Start came during the hold (the token was
         * voided). Returning 30 ms later lets the event handler push this index again BEFORE this feed thread receives the
         * seek's "empty your list" messages, so every input index is lost (the n11_mvs1 order; otherwise it is a race). */
        if (test_held) Sleep(30);
        RET(ST_OK);
        return;
    }
    if ((flags & FLAG_EOS) && d->eos_in) {            /* an index the game acquired before its first end of stream: taken, nothing comes out */
        if (sample) IMFSample_Release(sample);
        d->in_state[i] = IN_CODEC;
        dec_unlock(d);
        dlog(d, "SendInput %d: end of stream again, kept (no output, not offered again until a flush)", i);
        RET(ST_OK);
        return;
    }
    /* MediaCodec after an end-of-stream input: one end-of-stream output, and no input buffer is offered again until a flush.
     * Before, every offered index came back and every end of stream the game sent again made an output (48 video and 64
     * audio end-of-stream "frames" filled the pools: SSBU_MOVIE_LOG of n11_rsf4), so the decoders never ran dry. */
    if (flags & FLAG_EOS) d->eos_in = 1;
    d->in_data[i].s = sample; d->in_data[i].ts = ts; d->in_data[i].flags = flags & FLAG_EOS;
    d->in_state[i] = IN_DECODING;
    d->dec_list[d->dec_n++] = i;
    int first_fmt = fmt_event_wanted(d);
    if (first_fmt) d->fmt_signalled = 1;
    if (d->in_count == 1 || (flags & FLAG_EOS)) printf("movie: Decoder(%s): %s queued (t=%.3f s)\n", d->is_video ? "video" : "audio", flags & FLAG_EOS ? "end of stream" : "first sample", ts / 1e6);
    int ev = dec_pump(d);
    int waiting = d->dec_n, ready = d->out_n;
    dec_unlock(d);
    dlog(d, "SendInput %d t=%.3f flags %x (ready %d, waiting for an output buffer %d)", i, ts / 1e6, flags, ready, waiting);
    if (first_fmt) signal_event(d, 2);
    dec_signal(d, ev);
    RET(ST_OK);
}

static void dec_AcquireOutputBufferIndex(Ctx *c) {    /* (int *index, int64 *timeUs, unsigned *flags, int *moreAvailable) */
    Dec *d = dec_of(A0);
    if (!d || !A1 || !A2 || !A3 || !A4) { RET(ST_INVALID); return; }    /* all four are required [subsdk 0x1e730] */
    if (!dec_enter(d)) { RET(ST_INVALID); return; }
    dec_error_check(d);
    int r = ST_NO_OUTPUT, idx = -1; int64_t ts = 0; uint32_t flags = 0; int more = 0;
    if (d->out_n > 0) {
        idx = d->out_list[0];
        memmove(d->out_list, d->out_list + 1, (size_t)(d->out_n - 1) * sizeof d->out_list[0]);
        more = --d->out_n;
        OutBuf *s = &d->out[idx];
        s->state = OUT_CLIENT; ts = s->ts; flags = s->flags;
        d->out_count++;
        r = ST_OK;
    }
    dec_unlock(d);
    wr32(A1, (uint32_t)idx);
    wr64(A2, (uint64_t)ts);
    wr32(A3, flags);
    wr32(A4, (uint32_t)more);
    dlog(d, "AcquireOutput -> %d t=%.3f flags %x (more %d)", idx, ts / 1e6, flags, more);
    RET(r);
}

/* Copies the decoded sample of slot i into the game's buffer; returns the number of bytes written. */
static size_t copy_sample(Dec *d, OutBuf *s, unsigned char *dst, size_t cap) {
    if (!s->s) return 0;
    IMFMediaBuffer *mb = NULL;
    if (FAILED(IMFSample_ConvertToContiguousBuffer(s->s, &mb)) || !mb) return 0;
    BYTE *data = NULL; DWORD len = 0;
    size_t written = 0;
    if (SUCCEEDED(IMFMediaBuffer_Lock(mb, &data, NULL, &len)) && data) {
        if (d->is_video) {
            int w = d->w, h = d->h;
            size_t ysize = (size_t)w * (size_t)h, uvrows = (size_t)((h + 1) / 2), need = ysize + (size_t)w * uvrows;
            long pitch = w;
            IMF2DBuffer *b2 = NULL; BYTE *scan = NULL; LONG p2 = 0;
            if (len != need && h > 0 && SUCCEEDED(IMFMediaBuffer_QueryInterface(mb, &IID_IMF2DBuffer, (void **)&b2))) {
                if (SUCCEEDED(IMF2DBuffer_Lock2D(b2, &scan, &p2)) && scan && p2 > 0) { data = scan; pitch = p2; }
                else { IMF2DBuffer_Release(b2); b2 = NULL; }
            }
            int rows = d->plane_h > h ? d->plane_h : h;   /* the H.264 transform's planes have 1088 rows for 1080 shown (plane_h is 0 on WebM) */
            if (!b2 && len != need && h > 0) pitch = (long)((len * 2 / 3) / (size_t)rows);   /* tightly packed rows of another stride */
            if (pitch < w) pitch = w;
            if (cap < need) { if (!d->warned_small) { d->warned_small = 1; printf("movie: game buffer of %zu bytes is smaller than a %dx%d NV12 frame (%zu)\n", cap, w, h, need); } }
            else {
                const unsigned char *src = data;
                for (int y = 0; y < h; y++) memcpy(dst + (size_t)y * w, src + (size_t)y * pitch, (size_t)w);
                const unsigned char *uv = src + (size_t)pitch * rows;
                for (size_t y = 0; y < uvrows; y++) memcpy(dst + ysize + y * (size_t)w, uv + y * (size_t)pitch, (size_t)w);
                written = need;
            }
            if (b2) { IMF2DBuffer_Unlock2D(b2); IMF2DBuffer_Release(b2); }
        } else {
            written = len < cap ? len : cap;
            memcpy(dst, data, written);
            if (len > cap && !d->warned_small) { d->warned_small = 1; printf("movie: game audio buffer of %zu bytes is smaller than a decoded block (%lu)\n", cap, len); }
        }
        IMFMediaBuffer_Unlock(mb);
    }
    IMFMediaBuffer_Release(mb);
    return written;
}

static void dec_GetOutputBuffer(Ctx *c) {             /* (int index, Buffer *out[, MediaData *format]) */
    Dec *d = dec_of(A0);
    int i = (int)A1;
    uint64_t b = A2;
    if (!d || !b || i < 0 || i >= d->nout) { RET(ST_INVALID); return; }
    if (!dec_enter(d)) { RET(ST_INVALID); return; }
    OutBuf *s = &d->out[i];
    int r = ST_OK;
    if (s->state != OUT_CLIENT) r = ST_INVALID;       /* not acquired, or voided by Flush */
    else {
        uint64_t base = rd64(b + B_BASE), cap = rd64(b + B_CAP);
        size_t n = base ? copy_sample(d, s, (unsigned char *)(uintptr_t)base, (size_t)cap) : 0;
        wr32(b + B_OFFSET, 0);
        wr32(b + B_SIZE, (uint32_t)n);
        wr64(b + B_I64, (uint64_t)s->ts);
        wr32(b + B_U32, s->flags);
        if (n) d->copied++;
        if (d->copied == 1 && n) printf("movie: Decoder(%s): first frame copied to the game (%zu bytes into a %llu-byte buffer at %llx, t=%.3f s, tick %llu)\n",
                                        d->is_video ? "video" : "audio", n, (unsigned long long)cap, (unsigned long long)base, s->ts / 1e6, (unsigned long long)GetTickCount64());
        else if (d->is_video && d->copied % 300 == 0 && n) printf("movie: %llu video frames delivered (t=%.1f s)\n", d->copied, s->ts / 1e6);
    }
    dec_unlock(d);
    if (r) dlog(d, "GetOutputBuffer %d REFUSED (not held by the game)", i);
    RET(r);
}

static void dec_GetOutputBufferWithFormat(Ctx *c) {
    Dec *d = dec_of(A0);
    MD *m = md_of(A3);
    if (dec_live(d) && m) dec_fill_format(d, m);      /* dec_GetOutputBuffer checks again under the lock */
    dec_GetOutputBuffer(c);
}

static void dec_GetOutputBufferSize(Ctx *c) {         /* (int *size, int *count) */
    Dec *d = dec_of(A0);
    if (!dec_live(d) || !A1) { RET(ST_INVALID); return; }
    int size = d->is_video ? d->w * d->h + 2 * ((d->w + 1) / 2) * ((d->h + 1) / 2) : 0x8000;
    wr32(A1, (uint32_t)size);
    if (A2) wr32(A2, 1);
    RET(ST_OK);
}

static void dec_ReleaseOutputBufferIndex(Ctx *c) {    /* (int index) */
    Dec *d = dec_of(A0);
    int i = (int)A1;
    if (!d || i < 0 || i >= d->nout) { RET(ST_INVALID); return; }
    if (!dec_enter(d)) { RET(ST_INVALID); return; }
    OutBuf *s = &d->out[i];
    int ev = 0, ok = s->state == OUT_CLIENT;
    if (ok) {
        if (s->s) IMFSample_Release(s->s);
        memset(s, 0, sizeof *s);
        ev = dec_pump(d);                             /* a waiting input can now be decoded into this buffer */
    }
    dec_unlock(d);
    dlog(d, "ReleaseOutput %d%s", i, ok ? "" : " IGNORED (not held by the game)");
    dec_signal(d, ev);
    RET(ST_OK);
}

/* ---------------------------------------------------------------- vtables and constructors */
static uint64_t g_ext_vtable[20], g_dec_vtable[20];
static CRITICAL_SECTION g_init_lock;

typedef struct { const char *name; ImportFn fn; } Slot_;
static void build_vtables(void) {
    static const Slot_ ext_slots[] = {
        {"movie::Extractor::~Extractor", ext_dtor}, {"movie::Extractor::~Extractor(delete)", ext_deleting_dtor},
        {"movie::Extractor::SetDataSource(path)", ext_SetDataSource_path}, {"movie::Extractor::SetDataSource(memory)", ext_SetDataSource_mem},
        {"movie::Extractor::GetTrackCount", ext_GetTrackCount}, {"movie::Extractor::GetTrackConfiguration", ext_GetTrackConfiguration},
        {"movie::Extractor::SelectTrack", ext_SelectTrack}, {"movie::Extractor::UnselectTrack", ext_UnselectTrack},
        {"movie::Extractor::SeekTo", ext_SeekTo}, {"movie::Extractor::GetTrackIndexForAvailableData", ext_GetTrackIndexForAvailableData},
        {"movie::Extractor::Read", ext_Read}, {"movie::Extractor::Advance", ext_Advance},
        {"movie::Extractor::GetSampleTime", ext_GetSampleTime}, {"movie::Extractor::GetSampleMetaData", ext_GetSampleMetaData},
        {"movie::Extractor::GetBufferedRange", ext_GetBufferedRange}, {"movie::Extractor::SetDataSource(reader)", ext_SetDataSource_reader},
    };
    static const Slot_ dec_slots[] = {
        {"movie::Decoder::~Decoder", dec_dtor}, {"movie::Decoder::~Decoder(delete)", dec_deleting_dtor},
        {"movie::Decoder::Configure", dec_Configure}, {"movie::Decoder::RegisterClientEvents", dec_RegisterClientEvents},
        {"movie::Decoder::GetOutputFormat", dec_GetOutputFormat}, {"movie::Decoder::Start", dec_Start},
        {"movie::Decoder::Stop", dec_Stop}, {"movie::Decoder::Reset", dec_Reset}, {"movie::Decoder::Flush", dec_Flush},
        {"movie::Decoder::AcquireInputBufferIndex", dec_AcquireInputBufferIndex}, {"movie::Decoder::GetInputBuffer", dec_GetInputBuffer},
        {"movie::Decoder::SendInputBufferForDecode", dec_SendInputBufferForDecode}, {"movie::Decoder::AcquireOutputBufferIndex", dec_AcquireOutputBufferIndex},
        {"movie::Decoder::GetOutputBuffer", dec_GetOutputBuffer}, {"movie::Decoder::GetOutputBufferSize", dec_GetOutputBufferSize},
        {"movie::Decoder::ReleaseOutputBufferIndex", dec_ReleaseOutputBufferIndex}, {"movie::Decoder::GetLastError", dec_GetLastError},
        {"movie::Decoder::GetOutputBuffer(format)", dec_GetOutputBufferWithFormat}, {"movie::Decoder::GetOutputBufferFormat", dec_GetOutputBufferFormat},
    };
    EnterCriticalSection(&g_init_lock);
    if (!g_ext_vtable[0]) {
        for (unsigned i = 0; i < sizeof ext_slots / sizeof ext_slots[0]; i++) g_ext_vtable[i] = hostfn_address(ext_slots[i].name, ext_slots[i].fn);
        for (unsigned i = 0; i < sizeof dec_slots / sizeof dec_slots[0]; i++) g_dec_vtable[i] = hostfn_address(dec_slots[i].name, dec_slots[i].fn);
    }
    LeaveCriticalSection(&g_init_lock);
}

static void extractor_ctor(Ctx *c) {                  /* Extractor(ContainerType) */
    build_vtables();
    Ext *e = calloc(1, sizeof *e);
    InitializeCriticalSection(&e->cs);
    wr64(A0, (uint64_t)(uintptr_t)g_ext_vtable);
    wr64(A0 + 8, (uint64_t)(uintptr_t)e);
    input_mark("movie");
    printf("movie: Extractor created (container type %u: %s) on Media Foundation\n", (unsigned)A1, A1 == 1 ? "mp4" : A1 == 2 ? "mkv" : A1 == 3 ? "webm" : "?");
}

static void decoder_ctor(Ctx *c) {                    /* Decoder(DecoderType, DecoderOutputFormat, DecoderMode, int) */
    build_vtables();
    Dec *d = calloc(1, sizeof *d);
    InitializeCriticalSection(&d->cs);
    d->type = (int)A1; d->fmt = (int)A2; d->mode = (int)A3;
    d->is_video = d->type >= 1 && d->type <= 3;
    d->nin = 8;                                       /* compressed-data buffers: only bound how far the feed runs ahead of the codec */
    d->nout = d->is_video ? 48 : 64;                                     /* decoded frames the game may hold or leave queued before the codec stalls: it queues more than a second of video before showing the first frame */
    d->slot = SLOT_BYTES;                             /* Configure enlarges the input buffers for an H.264 elementary stream */
    d->mem = calloc((size_t)d->nin, d->slot);
    d->guest = A0;
    wr64(A0, (uint64_t)(uintptr_t)g_dec_vtable);
    wr64(A0 + 8, (uint64_t)(uintptr_t)d);
    dec_listed(d, 1);                                 /* g_dec_live: dec_of trusts listed decoders only */
    printf("movie: Decoder created (type %d = %s, output format %d, mode %d, %d)\n", d->type,
           d->type == 1 ? "H.264" : d->type == 2 ? "VP8" : d->type == 3 ? "VP9" : d->type == 4 ? "AAC" : d->type == 5 ? "Vorbis" : "?",
           d->fmt, d->mode, (int)A4);
    if (d->is_video && d->fmt != 4) printf("movie: WARNING output format %d requested, only 4 (NV12) is produced\n", d->fmt);
}

/* ---------------------------------------------------------------- the game's audio output object (movie player)
 * Layout used [game 0x71036f5720 ctor, 0x71036f5c10 Init, 0x71036f5170 output handler, 0x71036f6070 Flush, 0x71036f5e50 Stop]:
 * +56 the pool block (count +68 x size +72 bytes, allocated by Init, freed by Stop), +88/+96 pending decoder outputs,
 * +112/+120 the pool (movie::Buffer, 64 bytes each, borrowed from the block), +136/+144 the second list, +160 the decoded-
 * block Buffer, +184 the object's mutex. Flush rebuilds the pool from +56 WITHOUT checking it: called by the movie Seek
 * [0x71036e7620, calls at 0x71036e77ac / 0x71036e7860] before Init has run (the boot resync coming early, as on a busy PC),
 * it made 16 Buffers at addresses 0, 0x2000, ...; Init then appends the real 16, the output handler copies the first decoded
 * block into pool[0] = address 0 (HOST EXCEPTION writing 0x0, f_75004de070 from 0x71036f537c; runs osk1, det_ga1).
 * With no block, Flush here only empties the lists (what it does before the rebuild), under the object's mutex. */
static ImportFn g_orig_aout_flush, g_mtx_lock, g_mtx_unlock;
static long long g_aout_flush_empty;
static void aout_flush_hook(Ctx *c, void *user) {
    (void)user;
    uint64_t o = c->x[0];
    if (!o || !g_mtx_lock || !g_mtx_unlock) { g_orig_aout_flush(c); return; }
    Ctx t = *c; t.x[0] = o + 184; g_mtx_lock(&t);
    int empty = rd64(o + 56) == 0;
    if (empty) {
        wr64(o + 96, rd64(o + 88));                       /* pending outputs dropped */
        for (uint64_t b = rd64(o + 112), e = rd64(o + 120); b < e; b += 64) if (rd8(b + B_OWNS)) buf_release(c, b);
        wr64(o + 120, rd64(o + 112));
        for (uint64_t b = rd64(o + 136), e = rd64(o + 144); b < e; b += 64) if (rd8(b + B_OWNS)) buf_release(c, b);
        wr64(o + 144, rd64(o + 136));
    }
    t = *c; t.x[0] = o + 184; g_mtx_unlock(&t);
    if (!empty) { g_orig_aout_flush(c); return; }
    if (++g_aout_flush_empty <= 3) printf("movie: audio output Flush before its Init (no pool block): lists emptied, no pool built\n");
}
int hook_install(uint64_t addr, void (*repl)(Ctx *, void *), void *user, ImportFn *orig);      /* fighter_sdk\hook_host.c (in nnro.c) */
static void aout_hooks(void) {
    static int done; if (done++) return;
    if (getenv("SSBU_MOVIE_NO_FLUSH_GUARD")) return;
    g_mtx_lock = import_lookup("_ZNSt3__15mutex4lockEv"); g_mtx_unlock = import_lookup("_ZNSt3__15mutex6unlockEv");
    int id = hook_install(GA(0x71036f6070ULL), aout_flush_hook, NULL, &g_orig_aout_flush);
    if (!id || !g_mtx_lock || !g_mtx_unlock) printf("movie: WARNING the audio output Flush guard is not installed (hook %d, mutex %d)\n", id, g_mtx_lock && g_mtx_unlock);
}

/* ---------------------------------------------------------------- free functions */
static void movie_SetAllocator(Ctx *c) {              /* (alloc, free, realloc, user) */
    aout_hooks();
    g_alloc_fn = A0; g_free_fn = A1; g_alloc_user = A3;
    printf("movie: SetAllocator(alloc %llx, free %llx, realloc %llx, user %llx)\n", (unsigned long long)A0, (unsigned long long)A1, (unsigned long long)A2, (unsigned long long)A3);
}
static void movie_SetCoreMask(Ctx *c) { (void)c; }
static int g_thread_priority;
static void movie_SetThreadPriority(Ctx *c) { g_thread_priority = (int)A0; }
static void movie_GetThreadPriority(Ctx *c) { RET(g_thread_priority); }

/* H.264 helpers (the game's elementary-stream path, not used by the WebM movies). */
static const uint8_t *find_start_code(const uint8_t *p, const uint8_t *end) {
    for (; p + 3 <= end; p++) if (p[0] == 0 && p[1] == 0 && p[2] == 1) return p;
    return NULL;
}
static void movie_GetH264NalUnitStartPositionAndNalSize(Ctx *c) {   /* (uint8_t **pos, size_t *remaining, uint8_t **nalStart, size_t *nalSize) -> bool */
    uint64_t ppos = A0, prem = A1, pstart = A2, psize = A3;
    if (!ppos || !prem || !pstart || !psize) { RET(0); return; }
    const uint8_t *p = (const uint8_t *)(uintptr_t)rd64(ppos), *end = p + rd64(prem);
    const uint8_t *sc = p ? find_start_code(p, end) : NULL;
    if (!sc) { RET(0); return; }
    const uint8_t *nal = sc + 3;
    const uint8_t *next = find_start_code(nal, end);
    const uint8_t *nal_end = next ? next : end;
    while (nal_end > nal && nal_end[-1] == 0) nal_end--;      /* a 4-byte start code's leading zero belongs to the next unit */
    wr64(pstart, (uint64_t)(uintptr_t)nal);
    wr64(psize, (uint64_t)(nal_end - nal));
    wr64(ppos, (uint64_t)(uintptr_t)(next ? next : end));
    wr64(prem, (uint64_t)(end - (next ? next : end)));
    RET(1);
}
typedef struct { const uint8_t *p; size_t n; size_t bit; } BitReader;
static unsigned br_bit(BitReader *b) { if (b->bit >= b->n * 8) return 0; unsigned v = (b->p[b->bit >> 3] >> (7 - (b->bit & 7))) & 1; b->bit++; return v; }
static unsigned br_bits(BitReader *b, int n) { unsigned v = 0; while (n-- > 0) v = (v << 1) | br_bit(b); return v; }
static unsigned br_ue(BitReader *b) { int z = 0; while (!br_bit(b) && z < 32) z++; return z ? ((1u << z) - 1 + br_bits(b, z)) : 0; }
static int br_se(BitReader *b) { unsigned v = br_ue(b); return (v & 1) ? (int)((v + 1) / 2) : -(int)(v / 2); }
static void movie_GetH264PropertiesFromSps(Ctx *c) {  /* (const uint8_t *sps, size_t len, int *width, int *height, double *frameRate) -> bool */
    int width = 0, height = 0;
    double fps = 0.0;
    if (!h264_sps_dims((const uint8_t *)(uintptr_t)A0, A1, &width, &height, &fps)) { RET(0); return; }
    if (A2) wr32(A2, (uint32_t)width);
    if (A3) wr32(A3, (uint32_t)height);
    if (A4) { uint64_t bits; memcpy(&bits, &fps, 8); wr64(A4, bits); }
    RET(1);
}
static int h264_sps_dims(const uint8_t *sps, size_t len, int *out_w, int *out_h, double *out_fps) {   /* sps = the NAL unit, header byte first */
    if (!sps || len < 4) return 0;
    uint8_t clean[512]; size_t n = 0;                 /* strip emulation prevention bytes */
    for (size_t i = 0; i < len && n < sizeof clean; i++) { if (i >= 2 && sps[i] == 3 && sps[i - 1] == 0 && sps[i - 2] == 0) continue; clean[n++] = sps[i]; }
    BitReader b = {clean, n, 0};
    if ((br_bits(&b, 8) & 0x1f) != 7) return 0;
    unsigned profile = br_bits(&b, 8); br_bits(&b, 16); br_ue(&b);
    unsigned chroma = 1;
    if (profile == 100 || profile == 110 || profile == 122 || profile == 244 || profile == 44 || profile == 83 || profile == 86 || profile == 118 || profile == 128) {
        chroma = br_ue(&b); if (chroma == 3) br_bit(&b);
        br_ue(&b); br_ue(&b); br_bit(&b);
        if (br_bit(&b)) for (int i = 0; i < (chroma != 3 ? 8 : 12); i++) if (br_bit(&b)) { int last = 8, nxt = 8; for (int j = 0; j < (i < 6 ? 16 : 64); j++) { if (nxt) { int delta = br_se(&b); nxt = (last + delta + 256) % 256; } last = nxt ? nxt : last; } }
    }
    br_ue(&b);
    unsigned poc = br_ue(&b);
    if (poc == 0) br_ue(&b);
    else if (poc == 1) { br_bit(&b); br_se(&b); br_se(&b); unsigned k = br_ue(&b); for (unsigned i = 0; i < k && i < 256; i++) br_se(&b); }
    br_ue(&b); br_bit(&b);
    unsigned wmb = br_ue(&b) + 1, hmap = br_ue(&b) + 1, frame_mbs_only = br_bit(&b);
    if (!frame_mbs_only) br_bit(&b);
    br_bit(&b);
    unsigned cl = 0, cr = 0, ct = 0, cb = 0;
    if (br_bit(&b)) { cl = br_ue(&b); cr = br_ue(&b); ct = br_ue(&b); cb = br_ue(&b); }
    unsigned sub_w = chroma == 3 ? 1 : 2, sub_h = chroma == 1 ? 2 : 1, unit_y = sub_h * (2 - frame_mbs_only);
    int width = (int)(wmb * 16 - sub_w * (cl + cr)), height = (int)((2 - frame_mbs_only) * hmap * 16 - unit_y * (ct + cb));
    double fps = 0.0;
    if (br_bit(&b)) {                                 /* VUI */
        if (br_bit(&b)) { if (br_bits(&b, 8) == 255) br_bits(&b, 32); }
        if (br_bit(&b)) br_bit(&b);
        if (br_bit(&b)) { br_bits(&b, 4); if (br_bit(&b)) br_bits(&b, 24); }
        if (br_bit(&b)) { br_ue(&b); br_ue(&b); }
        if (br_bit(&b)) { unsigned num = br_bits(&b, 32), den = br_bits(&b, 32); if (num) fps = (double)den / (2.0 * num); }
    }
    *out_w = width; *out_h = height; *out_fps = fps;
    return 1;
}
/* The format the game passes to Decoder::Configure for an H.264 elementary stream. The parameter sets are copied (with
 * start codes, ready to go in front of the first unit) because the game's buffers do not outlive this call: the copy is
 * an owned MD_BUF entry of the MediaData (freed with it, copied with it), and dec_Configure keeps its own copy in d->csd
 * (freed by h264_close). */
static void movie_CreateH264DecoderConfigurationData(Ctx *c) {   /* (sps, spsLen, pps, ppsLen, MediaData *out) */
    MD *m = md_of(A4);
    const uint8_t *sps = (const uint8_t *)(uintptr_t)A0, *pps = (const uint8_t *)(uintptr_t)A2;
    size_t sl = A1, pl = A3;
    if (!m) { RET(ST_INVALID); return; }
    if (!h264_available()) {                          /* as before the H.264 path existed */
        md_set_str(m, "mime", "video/avc");
        md_set_i64(m, "csd-0-ptr", A0); md_set_i64(m, "csd-0-size", A1);
        md_set_i64(m, "csd-1-ptr", A2); md_set_i64(m, "csd-1-size", A3);
        printf("movie: CreateH264DecoderConfigurationData(sps %zu bytes, pps %zu bytes): no H.264 decoder\n", sl, pl);
        RET(ST_UNSUPPORTED);
        return;
    }
    if (!sps || !sl || sl > 4096 || pl > 4096 || (pl && !pps)) { RET(ST_INVALID); return; }
    size_t csd_len = 4 + sl + (pl ? 4 + pl : 0);
    unsigned char *csd = malloc(csd_len);
    if (!csd) { printf("movie: CreateH264DecoderConfigurationData: no memory for %zu bytes\n", csd_len); RET(ST_FAILED); return; }
    static const unsigned char sc[4] = {0, 0, 0, 1};
    memcpy(csd, sc, 4); memcpy(csd + 4, sps, sl);
    if (pl) { memcpy(csd + 4 + sl, sc, 4); memcpy(csd + 8 + sl, pps, pl); }
    int w = 0, h = 0; double fps = 0;
    int dims = h264_sps_dims(sps, sl, &w, &h, &fps);
    md_set_str(m, "mime", "video/avc");
    md_set_buf_owned(m, "nn-h264-csd", csd, csd_len); /* the MediaData owns csd from here (freed at once if it is full) */
    md_set_i64(m, "csd-0-ptr", A0); md_set_i64(m, "csd-0-size", A1);
    md_set_i64(m, "csd-1-ptr", A2); md_set_i64(m, "csd-1-size", A3);
    if (dims) { md_set_i32(m, "width", w); md_set_i32(m, "height", h); }
    printf("movie: CreateH264DecoderConfigurationData(sps %zu bytes, pps %zu bytes): %dx%d, %.2f frames/s\n", sl, pl, w, h, fps);
    RET(ST_OK);
}

/* ---------------------------------------------------------------- registration */
static const ImportDef movie_mf_imports[] = {
    {"_ZN5movie9ExtractorC1ENS_13ContainerTypeE", extractor_ctor},
    {"_ZN5movie9ExtractorC2ENS_13ContainerTypeE", extractor_ctor},
    {"_ZN5movie7DecoderC1ENS_11DecoderTypeENS_19DecoderOutputFormatENS_11DecoderModeEi", decoder_ctor},
    {"_ZN5movie7DecoderC2ENS_11DecoderTypeENS_19DecoderOutputFormatENS_11DecoderModeEi", decoder_ctor},
    {"_ZN5movie12SetAllocatorEPFPvmmS0_EPFvS0_S0_EPFS0_S0_mS0_ES0_", movie_SetAllocator},
    {"_ZN5movie11SetCoreMaskEm", movie_SetCoreMask},
    {"_ZN5movie17SetThreadPriorityEi", movie_SetThreadPriority},
    {"_ZN5movie17GetThreadPriorityEv", movie_GetThreadPriority},
    {"_ZN5movie34CreateH264DecoderConfigurationDataEPKhmS1_mPNS_9MediaDataE", movie_CreateH264DecoderConfigurationData},
    {"_ZN5movie37GetH264NalUnitStartPositionAndNalSizeEPPhPmS1_S2_", movie_GetH264NalUnitStartPositionAndNalSize},
    {"_ZN5movie37GetH264PropertiresFromSeqParamSetDataEPKhmPiS2_Pd", movie_GetH264PropertiesFromSps},
    /* movie::Buffer */
    {"_ZN5movie6BufferC1Ev", buf_ctor}, {"_ZN5movie6BufferC2Ev", buf_ctor},
    {"_ZN5movie6BufferC1Em", buf_ctor_size}, {"_ZN5movie6BufferC2Em", buf_ctor_size},
    {"_ZN5movie6BufferC1EPvm", buf_ctor_data}, {"_ZN5movie6BufferC2EPvm", buf_ctor_data},
    {"_ZN5movie6BufferC1ERKS0_", buf_copy_ctor}, {"_ZN5movie6BufferC2ERKS0_", buf_copy_ctor},
    {"_ZN5movie6BufferD1Ev", buf_dtor}, {"_ZN5movie6BufferD2Ev", buf_dtor},
    {"_ZN5movie6BufferaSERKS0_", buf_assign},
    {"_ZN5movie6Buffer18SetDataAndCapacityEPvm", buf_SetDataAndCapacity}, {"_ZN5movie6Buffer11SetCapacityEm", buf_SetCapacity},
    {"_ZN5movie6Buffer8SetRangeEii", buf_SetRange}, {"_ZN5movie6Buffer4SwapERS0_", buf_Swap},
    {"_ZNK5movie6Buffer4BaseEv", buf_Base}, {"_ZNK5movie6Buffer4DataEv", buf_Data}, {"_ZNK5movie6Buffer4SizeEv", buf_Size},
    {"_ZNK5movie6Buffer6OffsetEv", buf_Offset}, {"_ZNK5movie6Buffer8CapacityEv", buf_Capacity},
    {"_ZN5movie6Buffer12SetInt32DataEi", buf_SetInt32Data}, {"_ZN5movie6Buffer12SetInt64DataEl", buf_SetInt64Data},
    {"_ZN5movie6Buffer13SetUint32DataEj", buf_SetUint32Data}, {"_ZNK5movie6Buffer12GetInt32DataEv", buf_GetInt32Data},
    {"_ZNK5movie6Buffer12GetInt64DataEv", buf_GetInt64Data}, {"_ZNK5movie6Buffer13GetUint32DataEv", buf_GetUint32Data},
    {"_ZN5movie6Buffer9SetNvnDevEPv", buf_SetNvnDev}, {"_ZNK5movie6Buffer9GetNvnDevEv", buf_GetNvnDev},
    {"_ZN5movie6Buffer10SetNvnSyncEPv", buf_SetNvnSync}, {"_ZNK5movie6Buffer10GetNvnSyncEv", buf_GetNvnSync},
    /* movie::MediaData */
    {"_ZN5movie9MediaDataC1Ev", mdata_ctor}, {"_ZN5movie9MediaDataC2Ev", mdata_ctor},
    {"_ZN5movie9MediaDataC1ERKS0_", mdata_copy_ctor}, {"_ZN5movie9MediaDataC2ERKS0_", mdata_copy_ctor},
    {"_ZN5movie9MediaDataD1Ev", mdata_dtor}, {"_ZN5movie9MediaDataD2Ev", mdata_dtor},
    {"_ZN5movie9MediaDataaSERKS0_", mdata_assign},
    {"_ZN5movie9MediaData5ClearEv", mdata_Clear},
    {"_ZN5movie9MediaData8SetInt32EPKci", mdata_SetInt32}, {"_ZN5movie9MediaData8SetInt64EPKcl", mdata_SetInt64},
    {"_ZN5movie9MediaData9SetStringEPKcS2_", mdata_SetString}, {"_ZN5movie9MediaData8SetFloatEPKcf", mdata_SetFloat},
    {"_ZN5movie9MediaData10SetPointerEPKcPv", mdata_SetPointer},
    {"_ZNK5movie9MediaData9FindInt32EPKcPi", mdata_FindInt32}, {"_ZNK5movie9MediaData9FindInt64EPKcPl", mdata_FindInt64},
    {"_ZNK5movie9MediaData10FindStringEPKcPS2_", mdata_FindString}, {"_ZNK5movie9MediaData11FindPointerEPKcPPv", mdata_FindPointer},
    {"_ZNK5movie9MediaData8ContainsEPKc", mdata_Contains}, {"_ZNK5movie9MediaData12CountEntriesEv", mdata_CountEntries},
};

/* SSBU_MOVIE_H264_TEST=<file> (test only): decodes an H.264 elementary stream (Annex B) through the path of the final
 * smash movies (h264_open, h264_send, h264_pump, copy_sample), one NAL unit per input buffer without its start code as
 * the game's helper GetH264NalUnitStartPositionAndNalSize cuts them, prints what came out and ends the process (exit
 * code 0 = every picture came out, the end of stream was delivered, nothing was thrown away). */
static void h264_selftest(const char *path) {
    FILE *f = fopen(path, "rb");
    if (!f) { printf("h264 test: cannot open %s\n", path); fflush(stdout); ExitProcess(1); }
    fseek(f, 0, SEEK_END); long n = ftell(f); fseek(f, 0, SEEK_SET);
    unsigned char *buf = n > 0 ? malloc((size_t)n) : NULL;
    if (!buf || fread(buf, 1, (size_t)n, f) != (size_t)n) { printf("h264 test: cannot read %s\n", path); fflush(stdout); ExitProcess(1); }
    fclose(f);
    com_init();
    Dec *d = calloc(1, sizeof *d);
    if (!d) { printf("h264 test: no memory\n"); fflush(stdout); ExitProcess(1); }
    InitializeCriticalSection(&d->cs);
    d->type = 1; d->fmt = 4; d->is_video = 1; d->nin = 8; d->nout = 48; d->h264 = 1; d->slot = 2u << 20;
    d->mem = calloc((size_t)d->nin, d->slot);
    if (!d->mem) { printf("h264 test: no memory\n"); fflush(stdout); ExitProcess(1); }
    const unsigned char *end = buf + n, *sps = NULL, *pps = NULL; size_t sl = 0, pl = 0;
    for (const unsigned char *p = find_start_code(buf, end); p && (!sps || !pps); ) {
        const unsigned char *nal = p + 3, *next = find_start_code(nal, end), *ne = next ? next : end;
        while (ne > nal && ne[-1] == 0) ne--;
        if (ne > nal && (nal[0] & 0x1f) == 7 && !sps) { sps = nal; sl = (size_t)(ne - nal); }
        if (ne > nal && (nal[0] & 0x1f) == 8 && !pps) { pps = nal; pl = (size_t)(ne - nal); }
        p = next;
    }
    if (!sps || !pps) { printf("h264 test: no SPS / PPS in %s\n", path); fflush(stdout); ExitProcess(1); }
    d->csd = malloc(8 + sl + pl);
    if (!d->csd) { printf("h264 test: no memory\n"); fflush(stdout); ExitProcess(1); }
    d->csd_len = 8 + sl + pl;
    memcpy(d->csd, "\0\0\0\1", 4); memcpy(d->csd + 4, sps, sl); memcpy(d->csd + 4 + sl, "\0\0\0\1", 4); memcpy(d->csd + 8 + sl, pps, pl);
    double fps = 0; h264_sps_dims(sps, sl, &d->w, &d->h, &fps);
    if (!h264_open(d)) { printf("h264 test: no decoder\n"); fflush(stdout); ExitProcess(1); }
    size_t cap = (size_t)d->w * d->h * 2;
    unsigned char *frame = malloc(cap ? cap : 1);
    if (!frame) { printf("h264 test: no memory\n"); fflush(stdout); ExitProcess(1); }
    /* the game's side: its feed thread fills every input buffer the decoder offers (one NAL unit each, then end of stream
     * into each further one), its render path takes one decoded frame per game frame */
    unsigned long long units = 0, pictures = 0, frames = 0, eos = 0, sum = 0, offers_after_eos = 0, game_frames = 0; double luma0 = -1;
    int64_t ts = 0;
    const unsigned char *p = find_start_code(buf, end);
    for (int i = 0; i < d->nin; i++) { d->in_state[i] = IN_OFFERED; d->in_list[i] = i; }
    d->in_n = d->nin;
    while (!eos && game_frames < 100000) {
        while (d->in_n > 0) {
            int i = d->in_list[0];
            memmove(d->in_list, d->in_list + 1, (size_t)(d->in_n - 1) * sizeof d->in_list[0]); d->in_n--;
            d->in_state[i] = IN_CLIENT; d->in_count++;
            if (!p) { h264_send(d, i, 0, 0, ts, FLAG_EOS); continue; }   /* the slots the game still held get one each, then are kept */
            const unsigned char *nal = p + 3, *next = find_start_code(nal, end), *ne = next ? next : end;
            while (ne > nal && ne[-1] == 0) ne--;
            size_t len = (size_t)(ne - nal);
            int type = len ? nal[0] & 0x1f : 0;
            memcpy(d->mem + (size_t)i * d->slot, nal, len < d->slot ? len : d->slot);
            units++;
            h264_send(d, i, 0, (int)(len < d->slot ? len : d->slot), ts, 0);
            if (type == 1 || type == 5) { pictures++; ts += (int64_t)(1e6 / (fps > 0 ? fps : 30)); }
            p = next;
        }
        game_frames++;
        if (d->out_n > 0) {                           /* one frame shown per game frame */
            int o = d->out_list[0];
            memmove(d->out_list, d->out_list + 1, (size_t)(d->out_n - 1) * sizeof d->out_list[0]); d->out_n--;
            size_t got = copy_sample(d, &d->out[o], frame, cap);
            if (got) {
                frames++;
                for (size_t k = 0; k < got; k += 97) sum = sum * 31 + frame[k];
                if (luma0 < 0) { double s = 0; for (int k = 0; k < d->w * d->h; k++) s += frame[k]; luma0 = s / ((double)d->w * d->h); }
            }
            if (d->out[o].flags & FLAG_EOS) eos++;
            if (d->out[o].s) IMFSample_Release(d->out[o].s);
            memset(&d->out[o], 0, sizeof d->out[o]);
            int before = d->in_n;
            h264_pump(d);
            if (d->eos_in && d->in_n > before) offers_after_eos += (unsigned long long)(d->in_n - before);   /* a slot handed out again */
        }
    }
    printf("h264 test: %s: %llu NAL units, %llu pictures sent, %llu frames out (%dx%d, %.2f/s, planes of %d rows) in %llu game frames, "
           "%llu frames thrown away, input buffers offered after the end of stream: %llu, first frame mean luma %.1f, checksum %016llx, end of stream %s\n",
           path, units, pictures, frames, d->w, d->h, fps, d->plane_h, game_frames, d->dropped, offers_after_eos, luma0, sum, eos ? "delivered" : "MISSING");
    fflush(stdout);
    ExitProcess(frames && frames == pictures && eos && !d->dropped && !offers_after_eos ? 0 : 1);
}

void register_movie_mf_imports(void) {
    if (getenv("SSBU_MOVIE_H264_TEST")) h264_selftest(getenv("SSBU_MOVIE_H264_TEST"));    /* test only: ends the process */
    const char *env = getenv("SSBU_MOVIE");
    if (env && atoi(env) == 0) { printf("movie: SSBU_MOVIE=0, keeping the failing placeholder\n"); return; }
    g_log = getenv("SSBU_MOVIE_LOG") ? (atoi(getenv("SSBU_MOVIE_LOG")) == 2 ? 2 : 1) : 0;
    if (getenv("SSBU_MOVIE_TEST_RESYNC")) sscanf(getenv("SSBU_MOVIE_TEST_RESYNC"), "%d,%d,%d,%d", &g_test_resync_flag, &g_test_resync_at, &g_test_resync_flag2, &g_test_resync_ms);
    InitializeCriticalSection(&g_init_lock);
    register_imports(movie_mf_imports, (int)(sizeof movie_mf_imports / sizeof movie_mf_imports[0]));
}
