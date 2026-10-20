/* Windows: the movie fallback for PCs whose Media Foundation cannot play the game's movies (no Web Media Extensions /
 * VP9 Video Extensions, a broken copy of them, Windows N without the Media Feature Pack). It is plat_mf.c, the Media
 * Foundation subset the Linux build implements on FFmpeg, compiled a second time here with every name it defines
 * prefixed ffmf_, so it lives beside the real Media Foundation; runtime/mf_ffmpeg.h is what nnmovie_mf.c sees of it.
 *
 * FFmpeg is not linked: its DLLs (an LGPL build with only the WebM demuxer and the VP9 / H.264 / Vorbis / Opus decoders,
 * scripts/ffmpeg/build_ffmpeg_win.sh; scripts/fetch_media.py downloads them, SHA-256 checked) are loaded at the first
 * use, from SSBU_FFMPEG_DIR or from the exe's folder. Without them the game runs as before and nothing here is called.
 * Compiled against the headers of that same FFmpeg build (deps/ffmpeg/include): the DLL names follow their major versions. */
#if defined(_WIN32) && defined(__has_include)
#if __has_include(<libavcodec/avcodec.h>)        /* else: no fallback (nnmovie_mf.c checks the same) */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>
#include <libavformat/avformat.h>
#include <libavcodec/avcodec.h>
#include <libswscale/swscale.h>
#include <libswresample/swresample.h>
#include <libavutil/channel_layout.h>
#include <libavutil/opt.h>
#include <libavutil/version.h>

/* ---- FFmpeg's functions, through pointers filled by ffmf_available() */
#define FFMF_AV_FUNCS(X) \
    X(U, av_channel_layout_default) X(U, av_frame_alloc) X(U, av_frame_free) X(U, av_frame_unref) X(U, av_free) X(U, av_freep) \
    X(U, av_malloc) X(U, av_rescale_q) X(U, av_rescale_rnd) X(U, av_strerror) X(U, av_version_info) \
    X(C, av_packet_alloc) X(C, av_packet_free) X(C, av_packet_move_ref) X(C, av_packet_unref) X(C, av_parser_close) \
    X(C, av_parser_init) X(C, av_parser_parse2) X(C, avcodec_alloc_context3) X(C, avcodec_find_decoder) \
    X(C, avcodec_flush_buffers) X(C, avcodec_free_context) X(C, avcodec_get_name) X(C, avcodec_open2) \
    X(C, avcodec_parameters_to_context) X(C, avcodec_receive_frame) X(C, avcodec_send_packet) X(C, avcodec_version) \
    X(F, av_read_frame) X(F, av_seek_frame) X(F, avformat_alloc_context) X(F, avformat_close_input) \
    X(F, avformat_find_stream_info) X(F, avformat_open_input) X(F, avio_alloc_context) X(F, avio_context_free) \
    X(R, swr_alloc_set_opts2) X(R, swr_convert) X(R, swr_free) X(R, swr_get_delay) X(R, swr_init) \
    X(S, sws_freeContext) X(S, sws_getCachedContext) X(S, sws_scale)
#define FFMF_PTR(lib, fn) static __typeof__(fn) *p_##fn;
FFMF_AV_FUNCS(FFMF_PTR)
#define av_channel_layout_default (*p_av_channel_layout_default)
#define av_frame_alloc (*p_av_frame_alloc)
#define av_frame_free (*p_av_frame_free)
#define av_frame_unref (*p_av_frame_unref)
#define av_free (*p_av_free)
#define av_freep (*p_av_freep)
#define av_malloc (*p_av_malloc)
#define av_rescale_q (*p_av_rescale_q)
#define av_rescale_rnd (*p_av_rescale_rnd)
#define av_strerror (*p_av_strerror)
#define av_version_info (*p_av_version_info)
#define av_packet_alloc (*p_av_packet_alloc)
#define av_packet_free (*p_av_packet_free)
#define av_packet_move_ref (*p_av_packet_move_ref)
#define av_packet_unref (*p_av_packet_unref)
#define av_parser_close (*p_av_parser_close)
#define av_parser_init (*p_av_parser_init)
#define av_parser_parse2 (*p_av_parser_parse2)
#define avcodec_alloc_context3 (*p_avcodec_alloc_context3)
#define avcodec_find_decoder (*p_avcodec_find_decoder)
#define avcodec_flush_buffers (*p_avcodec_flush_buffers)
#define avcodec_free_context (*p_avcodec_free_context)
#define avcodec_get_name (*p_avcodec_get_name)
#define avcodec_open2 (*p_avcodec_open2)
#define avcodec_parameters_to_context (*p_avcodec_parameters_to_context)
#define avcodec_receive_frame (*p_avcodec_receive_frame)
#define avcodec_send_packet (*p_avcodec_send_packet)
#define avcodec_version (*p_avcodec_version)
#define av_read_frame (*p_av_read_frame)
#define av_seek_frame (*p_av_seek_frame)
#define avformat_alloc_context (*p_avformat_alloc_context)
#define avformat_close_input (*p_avformat_close_input)
#define avformat_find_stream_info (*p_avformat_find_stream_info)
#define avformat_open_input (*p_avformat_open_input)
#define avio_alloc_context (*p_avio_alloc_context)
#define avio_context_free (*p_avio_context_free)
#define swr_alloc_set_opts2 (*p_swr_alloc_set_opts2)
#define swr_convert (*p_swr_convert)
#define swr_free (*p_swr_free)
#define swr_get_delay (*p_swr_get_delay)
#define swr_init (*p_swr_init)
#define sws_freeContext (*p_sws_freeContext)
#define sws_getCachedContext (*p_sws_getCachedContext)
#define sws_scale (*p_sws_scale)

/* ---- the tag word every object of plat_mf.c starts with here (mf_ffmpeg.h: FFMF_IS) */
const char ffmf_tag[1];
#define FFMF_HEAD const void *ffmf_tag_word;
#define FFMF_INIT(p) ((p)->ffmf_tag_word = ffmf_tag)

/* ---- plat/mfapi.h and plat_mf.c under ffmf_ names: none of them may meet Media Foundation's own (the headers' or the
 * import libraries'). The Linux stand-in for <windows.h> is skipped: the real one is already in. */
#define PLAT_WINDOWS_H
#undef REFIID
#undef IsEqualIID
#undef STDMETHODCALLTYPE
#undef E_NOINTERFACE
#undef E_OUTOFMEMORY
#undef E_POINTER
#undef CLASS_E_NOAGGREGATION
#define REFIID ffmf_REFIID
#define VARTYPE ffmf_VARTYPE
#define PROPVARIANT ffmf_PROPVARIANT
#define IUnknown ffmf_IUnknown
#define IClassFactory ffmf_IClassFactory
#define IClassFactoryVtbl ffmf_IClassFactoryVtbl
#define IStream ffmf_IStream
#define IMFByteStream ffmf_IMFByteStream
#define IMFAttributes ffmf_IMFAttributes
#define IMFSourceReader ffmf_IMFSourceReader
#define IMFMediaType ffmf_IMFMediaType
#define IMFSample ffmf_IMFSample
#define IMFMediaBuffer ffmf_IMFMediaBuffer
#define IMF2DBuffer ffmf_IMF2DBuffer
#define IMFTransform ffmf_IMFTransform
#define IMFActivate ffmf_IMFActivate
#define IMFCollection ffmf_IMFCollection
#define MFT_REGISTER_TYPE_INFO ffmf_MFT_REGISTER_TYPE_INFO
#define MFT_OUTPUT_STREAM_INFO ffmf_MFT_OUTPUT_STREAM_INFO
#define MFT_OUTPUT_DATA_BUFFER ffmf_MFT_OUTPUT_DATA_BUFFER
#define MFT_MESSAGE_TYPE ffmf_MFT_MESSAGE_TYPE
#define GUID_NULL ffmf_GUID_NULL
#define IID_IUnknown ffmf_IID_IUnknown
#define IID_IClassFactory ffmf_IID_IClassFactory
#define IID_IMFAttributes ffmf_IID_IMFAttributes
#define IID_IMF2DBuffer ffmf_IID_IMF2DBuffer
#define IID_IMFTransform ffmf_IID_IMFTransform
#define MF_MT_MAJOR_TYPE ffmf_MF_MT_MAJOR_TYPE
#define MF_MT_SUBTYPE ffmf_MF_MT_SUBTYPE
#define MF_MT_FRAME_SIZE ffmf_MF_MT_FRAME_SIZE
#define MF_MT_FRAME_RATE ffmf_MF_MT_FRAME_RATE
#define MF_MT_AUDIO_SAMPLES_PER_SECOND ffmf_MF_MT_AUDIO_SAMPLES_PER_SECOND
#define MF_MT_AUDIO_NUM_CHANNELS ffmf_MF_MT_AUDIO_NUM_CHANNELS
#define MF_MT_AUDIO_BITS_PER_SAMPLE ffmf_MF_MT_AUDIO_BITS_PER_SAMPLE
#define MF_MT_INTERLACE_MODE ffmf_MF_MT_INTERLACE_MODE
#define MF_PD_DURATION ffmf_MF_PD_DURATION
#define MF_BYTESTREAM_CONTENT_TYPE ffmf_MF_BYTESTREAM_CONTENT_TYPE
#define MF_BYTESTREAM_ORIGIN_NAME ffmf_MF_BYTESTREAM_ORIGIN_NAME
#define MFMediaType_Video ffmf_MFMediaType_Video
#define MFMediaType_Audio ffmf_MFMediaType_Audio
#define MFVideoFormat_NV12 ffmf_MFVideoFormat_NV12
#define MFVideoFormat_H264 ffmf_MFVideoFormat_H264
#define MFAudioFormat_PCM ffmf_MFAudioFormat_PCM
#define MFAudioFormat_Float ffmf_MFAudioFormat_Float
#define MFT_FRIENDLY_NAME_Attribute ffmf_MFT_FRIENDLY_NAME_Attribute
#define MFT_CATEGORY_VIDEO_DECODER ffmf_MFT_CATEGORY_VIDEO_DECODER
#define MFT_CATEGORY_AUDIO_DECODER ffmf_MFT_CATEGORY_AUDIO_DECODER
#define MFStartup ffmf_MFStartup
#define SHCreateMemStream ffmf_SHCreateMemStream
#define IStream_Release ffmf_IStream_Release
#define MFCreateMFByteStreamOnStream ffmf_MFCreateMFByteStreamOnStream
#define IMFByteStream_QueryInterface ffmf_IMFByteStream_QueryInterface
#define IMFByteStream_Release ffmf_IMFByteStream_Release
#define IMFAttributes_SetString ffmf_IMFAttributes_SetString
#define IMFAttributes_Release ffmf_IMFAttributes_Release
#define MFCreateSourceReaderFromByteStream ffmf_MFCreateSourceReaderFromByteStream
#define IMFSourceReader_Release ffmf_IMFSourceReader_Release
#define IMFSourceReader_GetPresentationAttribute ffmf_IMFSourceReader_GetPresentationAttribute
#define IMFSourceReader_SetStreamSelection ffmf_IMFSourceReader_SetStreamSelection
#define IMFSourceReader_GetNativeMediaType ffmf_IMFSourceReader_GetNativeMediaType
#define IMFSourceReader_GetCurrentMediaType ffmf_IMFSourceReader_GetCurrentMediaType
#define IMFSourceReader_SetCurrentMediaType ffmf_IMFSourceReader_SetCurrentMediaType
#define IMFSourceReader_SetCurrentPosition ffmf_IMFSourceReader_SetCurrentPosition
#define IMFSourceReader_ReadSample ffmf_IMFSourceReader_ReadSample
#define MFCreateMediaType ffmf_MFCreateMediaType
#define IMFMediaType_Release ffmf_IMFMediaType_Release
#define IMFMediaType_SetGUID ffmf_IMFMediaType_SetGUID
#define IMFMediaType_GetGUID ffmf_IMFMediaType_GetGUID
#define IMFMediaType_SetUINT32 ffmf_IMFMediaType_SetUINT32
#define IMFMediaType_GetUINT32 ffmf_IMFMediaType_GetUINT32
#define IMFMediaType_SetUINT64 ffmf_IMFMediaType_SetUINT64
#define IMFMediaType_GetUINT64 ffmf_IMFMediaType_GetUINT64
#define IMFSample_Release ffmf_IMFSample_Release
#define IMFSample_ConvertToContiguousBuffer ffmf_IMFSample_ConvertToContiguousBuffer
#define IMFMediaBuffer_Lock ffmf_IMFMediaBuffer_Lock
#define IMFMediaBuffer_Unlock ffmf_IMFMediaBuffer_Unlock
#define IMFMediaBuffer_Release ffmf_IMFMediaBuffer_Release
#define IMFMediaBuffer_QueryInterface ffmf_IMFMediaBuffer_QueryInterface
#define IMF2DBuffer_Lock2D ffmf_IMF2DBuffer_Lock2D
#define IMF2DBuffer_Unlock2D ffmf_IMF2DBuffer_Unlock2D
#define IMF2DBuffer_Release ffmf_IMF2DBuffer_Release
#define MFCreateSample ffmf_MFCreateSample
#define MFCreateMemoryBuffer ffmf_MFCreateMemoryBuffer
#define IMFSample_AddBuffer ffmf_IMFSample_AddBuffer
#define IMFSample_SetSampleTime ffmf_IMFSample_SetSampleTime
#define IMFSample_GetSampleTime ffmf_IMFSample_GetSampleTime
#define IMFMediaBuffer_SetCurrentLength ffmf_IMFMediaBuffer_SetCurrentLength
#define MFTEnumEx ffmf_MFTEnumEx
#define MFTRegisterLocal ffmf_MFTRegisterLocal
#define IMFActivate_ActivateObject ffmf_IMFActivate_ActivateObject
#define IMFActivate_GetString ffmf_IMFActivate_GetString
#define IMFActivate_Release ffmf_IMFActivate_Release
#define IMFCollection_Release ffmf_IMFCollection_Release
#define IMFTransform_SetInputType ffmf_IMFTransform_SetInputType
#define IMFTransform_GetOutputAvailableType ffmf_IMFTransform_GetOutputAvailableType
#define IMFTransform_SetOutputType ffmf_IMFTransform_SetOutputType
#define IMFTransform_GetOutputStreamInfo ffmf_IMFTransform_GetOutputStreamInfo
#define IMFTransform_ProcessMessage ffmf_IMFTransform_ProcessMessage
#define IMFTransform_ProcessInput ffmf_IMFTransform_ProcessInput
#define IMFTransform_ProcessOutput ffmf_IMFTransform_ProcessOutput
#define IMFTransform_Release ffmf_IMFTransform_Release
#include "plat/mfapi.h"
/* the arrays MFTEnumEx hands out are freed by nnmovie_mf.c with the real CoTaskMemFree */
#undef CoTaskMemAlloc
#undef CoTaskMemFree
__declspec(dllimport) LPVOID WINAPI CoTaskMemAlloc(SIZE_T cb);
__declspec(dllimport) void WINAPI CoTaskMemFree(LPVOID pv);

#include "plat_mf.c"

/* ---- loading the DLLs */
#define FFMF_STR2(x) #x
#define FFMF_STR(x) FFMF_STR2(x)
static HMODULE load_from(const WCHAR *dir, const char *name) {
    WCHAR path[MAX_PATH + 64];
    if (_snwprintf(path, MAX_PATH + 63, L"%ls\\%hs", dir, name) < 0) return NULL;
    path[MAX_PATH + 63] = 0;
    /* the folder of the DLL first for ITS imports (the other FFmpeg DLLs): never a same-named copy elsewhere on PATH */
    return LoadLibraryExW(path, NULL, LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_SYSTEM32);
}
/* 1 when the FFmpeg DLLs are there and complete (loaded once; the result is kept). */
int ffmf_available(void) {
    static volatile LONG state = -1;                  /* -1 unknown, 0 missing, 1 ready */
    static SRWLOCK lock = SRWLOCK_INIT;
    if (state >= 0) return state;
    AcquireSRWLockExclusive(&lock);
    if (state < 0) {
        static const char *const names[5] = {"avutil-" FFMF_STR(LIBAVUTIL_VERSION_MAJOR) ".dll", "swresample-" FFMF_STR(LIBSWRESAMPLE_VERSION_MAJOR) ".dll",
                                             "swscale-" FFMF_STR(LIBSWSCALE_VERSION_MAJOR) ".dll", "avcodec-" FFMF_STR(LIBAVCODEC_VERSION_MAJOR) ".dll",
                                             "avformat-" FFMF_STR(LIBAVFORMAT_VERSION_MAJOR) ".dll"};
        WCHAR dirs[2][MAX_PATH];
        int nd = 0;
        DWORD k = GetEnvironmentVariableW(L"SSBU_FFMPEG_DIR", dirs[nd], MAX_PATH);
        if (k && k < MAX_PATH) nd++;
        k = GetModuleFileNameW(NULL, dirs[nd], MAX_PATH);
        if (k && k < MAX_PATH) { WCHAR *s = wcsrchr(dirs[nd], L'\\'); if (s) { *s = 0; nd++; } }
        HMODULE m[5] = {0};
        int d = 0, ok = 0;
        for (; d < nd && !ok; d++) {
            ok = 1;
            for (int i = 0; i < 5 && ok; i++) ok = (m[i] = load_from(dirs[d], names[i])) != NULL;
            if (!ok) for (int i = 0; i < 5; i++) if (m[i]) { FreeLibrary(m[i]); m[i] = NULL; }
        }
        const char *missing = NULL;
        if (ok) {
            HMODULE U = m[0], R = m[1], S = m[2], C = m[3], F = m[4];
#define FFMF_GET(lib, fn) if (!missing && !(p_##fn = (__typeof__(p_##fn))(void *)GetProcAddress(lib, #fn))) missing = #fn;
            FFMF_AV_FUNCS(FFMF_GET)
#undef FFMF_GET
            if (!missing && (avcodec_version() >> 16) != LIBAVCODEC_VERSION_MAJOR) missing = "avcodec_version (another major version)";
            if (!missing && !avcodec_find_decoder(AV_CODEC_ID_VP9)) missing = "the VP9 decoder";
            if (!missing && !avcodec_find_decoder(AV_CODEC_ID_VORBIS)) missing = "the Vorbis decoder";
        }
        if (ok && !missing) printf("movie: FFmpeg fallback ready: FFmpeg %s (libavcodec %u.%u) from %ls\n", av_version_info(),
                                   avcodec_version() >> 16, (avcodec_version() >> 8) & 0xff, dirs[d - 1]);
        else if (ok) printf("movie: the FFmpeg DLLs in %ls cannot be used: no %s\n", dirs[d - 1], missing);
        else printf("movie: no FFmpeg DLLs (%s ...) in %sthe exe's folder: no fallback for the movies\n", names[3], nd > 1 ? "SSBU_FFMPEG_DIR nor " : "");
        InterlockedExchange(&state, ok && !missing);
    }
    ReleaseSRWLockExclusive(&lock);
    return state;
}
#endif
#endif
