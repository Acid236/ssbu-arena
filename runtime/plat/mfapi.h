/* Linux build: the Media Foundation subset nnmovie_mf.c uses (source reader over an in-memory byte stream, decoded
 * NV12 video and 16-bit PCM audio; the H.264 decoder transform the final smash movies use), implemented on FFmpeg's
 * libavformat / libavcodec in plat_mf.c. mfidl.h,
 * mfreadwrite.h and mferror.h resolve to this file. Interfaces are opaque structures; the COBJMACROS-style calls of
 * the Windows headers are plain functions here. */
#ifndef PLAT_MFAPI_H
#define PLAT_MFAPI_H
#include "windows.h"

typedef struct IStream IStream;
typedef struct IMFByteStream IMFByteStream;
typedef struct IMFAttributes IMFAttributes;
typedef struct IMFSourceReader IMFSourceReader;
typedef struct IMFMediaType IMFMediaType;
typedef struct IMFSample IMFSample;
typedef struct IMFMediaBuffer IMFMediaBuffer;
typedef struct IMF2DBuffer IMF2DBuffer;
typedef unsigned short VARTYPE;
typedef struct { VARTYPE vt; WORD r1, r2, r3; union { LARGE_INTEGER hVal; ULARGE_INTEGER uhVal; LONG lVal; ULONG ulVal; double dblVal; void *ptr; }; } PROPVARIANT;
#define VT_EMPTY 0
#define VT_I8 20
#define VT_UI8 21
#define PropVariantInit(p) memset((p), 0, sizeof(PROPVARIANT))
#define PropVariantClear(p) (memset((p), 0, sizeof(PROPVARIANT)), S_OK)

#define CoInitializeEx(r, f) S_OK      /* no COM on Linux: plat_mf.c's objects are plain C */
#define COINIT_MULTITHREADED 0
#define MF_VERSION 0x20070
#define MFSTARTUP_FULL 0
HRESULT MFStartup(ULONG version, DWORD flags);

#define E_NOINTERFACE ((HRESULT)0x80004002)
#define E_OUTOFMEMORY ((HRESULT)0x8007000E)
#define MF_E_INVALIDSTREAMNUMBER ((HRESULT)0xC00D36B3)
#define MF_E_INVALIDMEDIATYPE ((HRESULT)0xC00D36B4)
#define MF_E_ATTRIBUTENOTFOUND ((HRESULT)0xC00D36E6)
#define MF_E_UNSUPPORTED_BYTESTREAM_TYPE ((HRESULT)0xC00D36C4)
#define MF_E_NOTACCEPTING ((HRESULT)0xC00D36B5)
#define MF_E_TRANSFORM_NEED_MORE_INPUT ((HRESULT)0xC00D6D72)
#define MF_E_TRANSFORM_STREAM_CHANGE ((HRESULT)0xC00D6D61)
#define MF_E_TRANSFORM_TYPE_NOT_SET ((HRESULT)0xC00D6D60)
#define MF_E_TOPO_CODEC_NOT_FOUND ((HRESULT)0xC00D5212)
#define E_POINTER ((HRESULT)0x80004003)
#ifndef E_NOTIMPL
#define E_NOTIMPL ((HRESULT)0x80004001)
#endif
#define CLASS_E_NOAGGREGATION ((HRESULT)0x80040110)

#define MF_SOURCE_READER_ALL_STREAMS 0xFFFFFFFEu
#define MF_SOURCE_READER_ANY_STREAM 0xFFFFFFFEu
#define MF_SOURCE_READER_FIRST_VIDEO_STREAM 0xFFFFFFFCu
#define MF_SOURCE_READER_FIRST_AUDIO_STREAM 0xFFFFFFFDu
#define MF_SOURCE_READER_MEDIASOURCE 0xFFFFFFFFu
#define MF_SOURCE_READERF_ERROR 0x1
#define MF_SOURCE_READERF_ENDOFSTREAM 0x2
#define MF_SOURCE_READERF_STREAMTICK 0x100

/* COM: only what the class factory of nnmovie_mf.c (the Windows Store Vorbis registration) needs to compile */
#define STDMETHODCALLTYPE
typedef const GUID *REFIID;
#define IsEqualIID(a, b) IsEqualGUID((a), (b))
typedef struct IUnknown IUnknown;
typedef struct IClassFactory IClassFactory;
typedef struct {
    HRESULT (*QueryInterface)(IClassFactory *This, REFIID riid, void **ppv);
    ULONG (*AddRef)(IClassFactory *This);
    ULONG (*Release)(IClassFactory *This);
    HRESULT (*CreateInstance)(IClassFactory *This, IUnknown *outer, REFIID riid, void **ppv);
    HRESULT (*LockServer)(IClassFactory *This, BOOL lock);
} IClassFactoryVtbl;
struct IClassFactory { IClassFactoryVtbl *lpVtbl; };
extern const GUID IID_IUnknown, IID_IClassFactory;
#define CoTaskMemAlloc(n) malloc(n)
#define CoTaskMemFree(p) free(p)

/* the GUIDs this subset knows (values of the real ones; only their identity matters here) */
extern const GUID GUID_NULL, IID_IMFAttributes, IID_IMF2DBuffer;
extern const GUID MF_MT_MAJOR_TYPE, MF_MT_SUBTYPE, MF_MT_FRAME_SIZE, MF_MT_FRAME_RATE, MF_MT_AUDIO_SAMPLES_PER_SECOND,
    MF_MT_AUDIO_NUM_CHANNELS, MF_MT_AUDIO_BITS_PER_SAMPLE, MF_PD_DURATION, MF_BYTESTREAM_CONTENT_TYPE, MF_BYTESTREAM_ORIGIN_NAME;
extern const GUID MFMediaType_Video, MFMediaType_Audio, MFVideoFormat_NV12, MFAudioFormat_PCM;
extern const GUID MFVideoFormat_H264, MFAudioFormat_Float, MF_MT_INTERLACE_MODE, MFT_FRIENDLY_NAME_Attribute, IID_IMFTransform,
    MFT_CATEGORY_VIDEO_DECODER, MFT_CATEGORY_AUDIO_DECODER;
#define MFVideoInterlace_Progressive 2

IStream *SHCreateMemStream(const BYTE *data, UINT size);    /* copies the bytes */
ULONG IStream_Release(IStream *s);
HRESULT MFCreateMFByteStreamOnStream(IStream *s, IMFByteStream **out);
HRESULT IMFByteStream_QueryInterface(IMFByteStream *b, const GUID *iid, void **out);
ULONG IMFByteStream_Release(IMFByteStream *b);
HRESULT IMFAttributes_SetString(IMFAttributes *a, const GUID *key, LPCWSTR value);
ULONG IMFAttributes_Release(IMFAttributes *a);
HRESULT MFCreateSourceReaderFromByteStream(IMFByteStream *b, IMFAttributes *attrs, IMFSourceReader **out);
ULONG IMFSourceReader_Release(IMFSourceReader *r);
HRESULT IMFSourceReader_GetPresentationAttribute(IMFSourceReader *r, DWORD stream, const GUID *key, PROPVARIANT *out);
HRESULT IMFSourceReader_SetStreamSelection(IMFSourceReader *r, DWORD stream, BOOL on);
HRESULT IMFSourceReader_GetNativeMediaType(IMFSourceReader *r, DWORD stream, DWORD index, IMFMediaType **out);
HRESULT IMFSourceReader_GetCurrentMediaType(IMFSourceReader *r, DWORD stream, IMFMediaType **out);
HRESULT IMFSourceReader_SetCurrentMediaType(IMFSourceReader *r, DWORD stream, DWORD *reserved, IMFMediaType *t);
HRESULT IMFSourceReader_SetCurrentPosition(IMFSourceReader *r, const GUID *format, const PROPVARIANT *pos);
HRESULT IMFSourceReader_ReadSample(IMFSourceReader *r, DWORD stream, DWORD control, DWORD *actual, DWORD *flags, LONGLONG *time, IMFSample **out);
HRESULT MFCreateMediaType(IMFMediaType **out);
ULONG IMFMediaType_Release(IMFMediaType *t);
HRESULT IMFMediaType_SetGUID(IMFMediaType *t, const GUID *key, const GUID *v);
HRESULT IMFMediaType_GetGUID(IMFMediaType *t, const GUID *key, GUID *v);
HRESULT IMFMediaType_SetUINT32(IMFMediaType *t, const GUID *key, UINT32 v);
HRESULT IMFMediaType_GetUINT32(IMFMediaType *t, const GUID *key, UINT32 *v);
HRESULT IMFMediaType_SetUINT64(IMFMediaType *t, const GUID *key, UINT64 v);
HRESULT IMFMediaType_GetUINT64(IMFMediaType *t, const GUID *key, UINT64 *v);
ULONG IMFSample_Release(IMFSample *s);
HRESULT IMFSample_ConvertToContiguousBuffer(IMFSample *s, IMFMediaBuffer **out);
HRESULT IMFMediaBuffer_Lock(IMFMediaBuffer *b, BYTE **data, DWORD *max, DWORD *len);
HRESULT IMFMediaBuffer_Unlock(IMFMediaBuffer *b);
ULONG IMFMediaBuffer_Release(IMFMediaBuffer *b);
HRESULT IMFMediaBuffer_QueryInterface(IMFMediaBuffer *b, const GUID *iid, void **out);   /* no IMF2DBuffer: frames are tightly packed */
HRESULT IMF2DBuffer_Lock2D(IMF2DBuffer *b, BYTE **scan0, LONG *pitch);
HRESULT IMF2DBuffer_Unlock2D(IMF2DBuffer *b);
ULONG IMF2DBuffer_Release(IMF2DBuffer *b);
HRESULT MFCreateSample(IMFSample **out);
HRESULT MFCreateMemoryBuffer(DWORD max, IMFMediaBuffer **out);
HRESULT IMFSample_AddBuffer(IMFSample *s, IMFMediaBuffer *b);       /* one buffer per sample in this subset */
HRESULT IMFSample_SetSampleTime(IMFSample *s, LONGLONG t);
HRESULT IMFSample_GetSampleTime(IMFSample *s, LONGLONG *t);
HRESULT IMFMediaBuffer_SetCurrentLength(IMFMediaBuffer *b, DWORD len);

/* ---- decoder transforms (MFT): only the H.264 video decoder, on libavcodec. MFTEnumEx also lists a Vorbis audio decoder
 * among the local ones, because the source reader above decodes Vorbis itself: the Store-decoder workaround of
 * nnmovie_mf.c then has nothing to do, as on a Windows PC with Web Media Extensions 2.x. That one cannot be activated. */
typedef struct IMFTransform IMFTransform;
typedef struct IMFActivate IMFActivate;
typedef struct IMFCollection IMFCollection;
typedef struct { GUID guidMajorType, guidSubtype; } MFT_REGISTER_TYPE_INFO;
typedef struct { DWORD dwFlags, cbSize, cbAlignment; } MFT_OUTPUT_STREAM_INFO;
typedef struct { DWORD dwStreamID; IMFSample *pSample; DWORD dwStatus; IMFCollection *pEvents; } MFT_OUTPUT_DATA_BUFFER;
#define MFT_ENUM_FLAG_SYNCMFT 0x1
#define MFT_ENUM_FLAG_ASYNCMFT 0x2
#define MFT_ENUM_FLAG_HARDWARE 0x4
#define MFT_ENUM_FLAG_FIELDOFUSE 0x8
#define MFT_ENUM_FLAG_LOCALMFT 0x10
#define MFT_ENUM_FLAG_TRANSCODE_ONLY 0x20
#define MFT_ENUM_FLAG_SORTANDFILTER 0x40
#define MFT_ENUM_FLAG_UNTRUSTED_STOREMFT 0x400
#define MFT_OUTPUT_STREAM_PROVIDES_SAMPLES 0x100
#define MFT_OUTPUT_STREAM_CAN_PROVIDE_SAMPLES 0x200
#define MFT_OUTPUT_DATA_BUFFER_FORMAT_CHANGE 0x100
typedef enum {
    MFT_MESSAGE_COMMAND_FLUSH = 0, MFT_MESSAGE_COMMAND_DRAIN = 1, MFT_MESSAGE_SET_D3D_MANAGER = 2,
    MFT_MESSAGE_NOTIFY_BEGIN_STREAMING = 0x10000000, MFT_MESSAGE_NOTIFY_END_STREAMING = 0x10000001,
    MFT_MESSAGE_NOTIFY_END_OF_STREAM = 0x10000002, MFT_MESSAGE_NOTIFY_START_OF_STREAM = 0x10000003
} MFT_MESSAGE_TYPE;
HRESULT MFTEnumEx(GUID category, UINT32 flags, const MFT_REGISTER_TYPE_INFO *in, const MFT_REGISTER_TYPE_INFO *out, IMFActivate ***acts, UINT32 *n);
HRESULT MFTRegisterLocal(IClassFactory *f, const GUID *category, LPCWSTR name, UINT32 flags, UINT32 nin, const MFT_REGISTER_TYPE_INFO *in,
                         UINT32 nout, const MFT_REGISTER_TYPE_INFO *out);
HRESULT IMFActivate_ActivateObject(IMFActivate *a, const GUID *iid, void **out);
HRESULT IMFActivate_GetString(IMFActivate *a, const GUID *key, LPWSTR out, UINT32 cch, UINT32 *len);
ULONG IMFActivate_Release(IMFActivate *a);
ULONG IMFCollection_Release(IMFCollection *c);
HRESULT IMFTransform_SetInputType(IMFTransform *t, DWORD stream, IMFMediaType *type, DWORD flags);
HRESULT IMFTransform_GetOutputAvailableType(IMFTransform *t, DWORD stream, DWORD index, IMFMediaType **out);
HRESULT IMFTransform_SetOutputType(IMFTransform *t, DWORD stream, IMFMediaType *type, DWORD flags);
HRESULT IMFTransform_GetOutputStreamInfo(IMFTransform *t, DWORD stream, MFT_OUTPUT_STREAM_INFO *info);
HRESULT IMFTransform_ProcessMessage(IMFTransform *t, MFT_MESSAGE_TYPE msg, ULONG_PTR param);
HRESULT IMFTransform_ProcessInput(IMFTransform *t, DWORD stream, IMFSample *s, DWORD flags);
HRESULT IMFTransform_ProcessOutput(IMFTransform *t, DWORD flags, DWORD count, MFT_OUTPUT_DATA_BUFFER *buffers, DWORD *status);
ULONG IMFTransform_Release(IMFTransform *t);
#endif
