/* Windows: what nnmovie_mf.c sees of the FFmpeg movie fallback (mf_ffmpeg.c). Include after the Media Foundation
 * headers (COBJMACROS).
 *
 * The fallback's objects are plat_mf.c's: plain C structures whose first word is the tag ffmf_tag, where a Media
 * Foundation COM object has its vtable. Each Media Foundation method call nnmovie_mf.c makes is redefined here to look at
 * that word: an FFmpeg object goes to its ffmf_ function, anything else to the vtable exactly as before. So a PC whose
 * Media Foundation plays the movies runs the same calls as without this file; the objects only meet their own kind
 * (a reader's samples, a transform's types and samples are made by the same side, see nnmovie_mf.c). */
#ifndef MF_FFMPEG_H
#define MF_FFMPEG_H

int ffmf_available(void);                             /* the FFmpeg DLLs are there (loads them once) */
extern const char ffmf_tag[1];
#define FFMF_IS(p) (*(const void *const *)(const void *)(p) == (const void *)ffmf_tag)

/* the free functions, under their own names: callers choose */
IStream *ffmf_SHCreateMemStream(const BYTE *data, UINT size);
ULONG ffmf_IStream_Release(IStream *s);
HRESULT ffmf_MFCreateMFByteStreamOnStream(IStream *s, IMFByteStream **out);
HRESULT ffmf_MFCreateSourceReaderFromByteStream(IMFByteStream *b, IMFAttributes *attrs, IMFSourceReader **out);
HRESULT ffmf_MFCreateMediaType(IMFMediaType **out);
HRESULT ffmf_MFCreateSample(IMFSample **out);
HRESULT ffmf_MFCreateMemoryBuffer(DWORD max, IMFMediaBuffer **out);
HRESULT ffmf_MFTEnumEx(GUID category, UINT32 flags, const MFT_REGISTER_TYPE_INFO *in, const MFT_REGISTER_TYPE_INFO *out, IMFActivate ***acts, UINT32 *n);

/* the methods: objects as void *, the rest as Media Foundation declares it */
ULONG ffmf_IMFByteStream_Release(void *o);
HRESULT ffmf_IMFByteStream_QueryInterface(void *o, REFIID iid, void **out);
ULONG ffmf_IMFAttributes_Release(void *o);
HRESULT ffmf_IMFAttributes_SetString(void *o, REFGUID key, LPCWSTR value);
ULONG ffmf_IMFSourceReader_Release(void *o);
HRESULT ffmf_IMFSourceReader_GetPresentationAttribute(void *o, DWORD stream, REFGUID key, PROPVARIANT *out);
HRESULT ffmf_IMFSourceReader_SetStreamSelection(void *o, DWORD stream, BOOL on);
HRESULT ffmf_IMFSourceReader_GetNativeMediaType(void *o, DWORD stream, DWORD index, IMFMediaType **out);
HRESULT ffmf_IMFSourceReader_GetCurrentMediaType(void *o, DWORD stream, IMFMediaType **out);
HRESULT ffmf_IMFSourceReader_SetCurrentMediaType(void *o, DWORD stream, DWORD *reserved, IMFMediaType *t);
HRESULT ffmf_IMFSourceReader_SetCurrentPosition(void *o, REFGUID format, const PROPVARIANT *pos);
HRESULT ffmf_IMFSourceReader_ReadSample(void *o, DWORD stream, DWORD control, DWORD *actual, DWORD *flags, LONGLONG *time, IMFSample **out);
ULONG ffmf_IMFMediaType_Release(void *o);
HRESULT ffmf_IMFMediaType_SetGUID(void *o, REFGUID key, REFGUID v);
HRESULT ffmf_IMFMediaType_GetGUID(void *o, REFGUID key, GUID *v);
HRESULT ffmf_IMFMediaType_SetUINT32(void *o, REFGUID key, UINT32 v);
HRESULT ffmf_IMFMediaType_GetUINT32(void *o, REFGUID key, UINT32 *v);
HRESULT ffmf_IMFMediaType_SetUINT64(void *o, REFGUID key, UINT64 v);
HRESULT ffmf_IMFMediaType_GetUINT64(void *o, REFGUID key, UINT64 *v);
ULONG ffmf_IMFSample_Release(void *o);
HRESULT ffmf_IMFSample_AddBuffer(void *o, IMFMediaBuffer *b);
HRESULT ffmf_IMFSample_ConvertToContiguousBuffer(void *o, IMFMediaBuffer **out);
HRESULT ffmf_IMFSample_GetSampleTime(void *o, LONGLONG *t);
HRESULT ffmf_IMFSample_SetSampleTime(void *o, LONGLONG t);
ULONG ffmf_IMFMediaBuffer_Release(void *o);
HRESULT ffmf_IMFMediaBuffer_Lock(void *o, BYTE **data, DWORD *max, DWORD *len);
HRESULT ffmf_IMFMediaBuffer_Unlock(void *o);
HRESULT ffmf_IMFMediaBuffer_QueryInterface(void *o, REFIID iid, void **out);
HRESULT ffmf_IMFMediaBuffer_SetCurrentLength(void *o, DWORD len);
ULONG ffmf_IMFActivate_Release(void *o);
HRESULT ffmf_IMFActivate_ActivateObject(void *o, REFIID iid, void **out);
HRESULT ffmf_IMFActivate_GetString(void *o, REFGUID key, LPWSTR out, UINT32 cch, UINT32 *len);
ULONG ffmf_IMFTransform_Release(void *o);
HRESULT ffmf_IMFTransform_SetInputType(void *o, DWORD stream, IMFMediaType *type, DWORD flags);
HRESULT ffmf_IMFTransform_GetOutputAvailableType(void *o, DWORD stream, DWORD index, IMFMediaType **out);
HRESULT ffmf_IMFTransform_SetOutputType(void *o, DWORD stream, IMFMediaType *type, DWORD flags);
HRESULT ffmf_IMFTransform_GetOutputStreamInfo(void *o, DWORD stream, MFT_OUTPUT_STREAM_INFO *info);
HRESULT ffmf_IMFTransform_ProcessMessage(void *o, MFT_MESSAGE_TYPE msg, ULONG_PTR param);
HRESULT ffmf_IMFTransform_ProcessInput(void *o, DWORD stream, IMFSample *s, DWORD flags);
HRESULT ffmf_IMFTransform_ProcessOutput(void *o, DWORD flags, DWORD count, MFT_OUTPUT_DATA_BUFFER *buffers, DWORD *status);

#define FFMF_M0(T, M, p) (FFMF_IS(p) ? ffmf_##T##_##M((void *)(p)) : (p)->lpVtbl->M(p))
#define FFMF_M(T, M, p, ...) (FFMF_IS(p) ? ffmf_##T##_##M((void *)(p), __VA_ARGS__) : (p)->lpVtbl->M(p, __VA_ARGS__))
#undef IMFByteStream_Release
#define IMFByteStream_Release(p) FFMF_M0(IMFByteStream, Release, p)
#undef IMFByteStream_QueryInterface
#define IMFByteStream_QueryInterface(p, ...) FFMF_M(IMFByteStream, QueryInterface, p, __VA_ARGS__)
#undef IMFAttributes_Release
#define IMFAttributes_Release(p) FFMF_M0(IMFAttributes, Release, p)
#undef IMFAttributes_SetString
#define IMFAttributes_SetString(p, ...) FFMF_M(IMFAttributes, SetString, p, __VA_ARGS__)
#undef IMFSourceReader_Release
#define IMFSourceReader_Release(p) FFMF_M0(IMFSourceReader, Release, p)
#undef IMFSourceReader_GetPresentationAttribute
#define IMFSourceReader_GetPresentationAttribute(p, ...) FFMF_M(IMFSourceReader, GetPresentationAttribute, p, __VA_ARGS__)
#undef IMFSourceReader_SetStreamSelection
#define IMFSourceReader_SetStreamSelection(p, ...) FFMF_M(IMFSourceReader, SetStreamSelection, p, __VA_ARGS__)
#undef IMFSourceReader_GetNativeMediaType
#define IMFSourceReader_GetNativeMediaType(p, ...) FFMF_M(IMFSourceReader, GetNativeMediaType, p, __VA_ARGS__)
#undef IMFSourceReader_GetCurrentMediaType
#define IMFSourceReader_GetCurrentMediaType(p, ...) FFMF_M(IMFSourceReader, GetCurrentMediaType, p, __VA_ARGS__)
#undef IMFSourceReader_SetCurrentMediaType
#define IMFSourceReader_SetCurrentMediaType(p, ...) FFMF_M(IMFSourceReader, SetCurrentMediaType, p, __VA_ARGS__)
#undef IMFSourceReader_SetCurrentPosition
#define IMFSourceReader_SetCurrentPosition(p, ...) FFMF_M(IMFSourceReader, SetCurrentPosition, p, __VA_ARGS__)
#undef IMFSourceReader_ReadSample
#define IMFSourceReader_ReadSample(p, ...) FFMF_M(IMFSourceReader, ReadSample, p, __VA_ARGS__)
#undef IMFMediaType_Release
#define IMFMediaType_Release(p) FFMF_M0(IMFMediaType, Release, p)
#undef IMFMediaType_SetGUID
#define IMFMediaType_SetGUID(p, ...) FFMF_M(IMFMediaType, SetGUID, p, __VA_ARGS__)
#undef IMFMediaType_GetGUID
#define IMFMediaType_GetGUID(p, ...) FFMF_M(IMFMediaType, GetGUID, p, __VA_ARGS__)
#undef IMFMediaType_SetUINT32
#define IMFMediaType_SetUINT32(p, ...) FFMF_M(IMFMediaType, SetUINT32, p, __VA_ARGS__)
#undef IMFMediaType_GetUINT32
#define IMFMediaType_GetUINT32(p, ...) FFMF_M(IMFMediaType, GetUINT32, p, __VA_ARGS__)
#undef IMFMediaType_SetUINT64
#define IMFMediaType_SetUINT64(p, ...) FFMF_M(IMFMediaType, SetUINT64, p, __VA_ARGS__)
#undef IMFMediaType_GetUINT64
#define IMFMediaType_GetUINT64(p, ...) FFMF_M(IMFMediaType, GetUINT64, p, __VA_ARGS__)
#undef IMFSample_Release
#define IMFSample_Release(p) FFMF_M0(IMFSample, Release, p)
#undef IMFSample_AddBuffer
#define IMFSample_AddBuffer(p, ...) FFMF_M(IMFSample, AddBuffer, p, __VA_ARGS__)
#undef IMFSample_ConvertToContiguousBuffer
#define IMFSample_ConvertToContiguousBuffer(p, ...) FFMF_M(IMFSample, ConvertToContiguousBuffer, p, __VA_ARGS__)
#undef IMFSample_GetSampleTime
#define IMFSample_GetSampleTime(p, ...) FFMF_M(IMFSample, GetSampleTime, p, __VA_ARGS__)
#undef IMFSample_SetSampleTime
#define IMFSample_SetSampleTime(p, ...) FFMF_M(IMFSample, SetSampleTime, p, __VA_ARGS__)
#undef IMFMediaBuffer_Release
#define IMFMediaBuffer_Release(p) FFMF_M0(IMFMediaBuffer, Release, p)
#undef IMFMediaBuffer_Lock
#define IMFMediaBuffer_Lock(p, ...) FFMF_M(IMFMediaBuffer, Lock, p, __VA_ARGS__)
#undef IMFMediaBuffer_Unlock
#define IMFMediaBuffer_Unlock(p) FFMF_M0(IMFMediaBuffer, Unlock, p)
#undef IMFMediaBuffer_QueryInterface
#define IMFMediaBuffer_QueryInterface(p, ...) FFMF_M(IMFMediaBuffer, QueryInterface, p, __VA_ARGS__)
#undef IMFMediaBuffer_SetCurrentLength
#define IMFMediaBuffer_SetCurrentLength(p, ...) FFMF_M(IMFMediaBuffer, SetCurrentLength, p, __VA_ARGS__)
#undef IMFActivate_Release
#define IMFActivate_Release(p) FFMF_M0(IMFActivate, Release, p)
#undef IMFActivate_ActivateObject
#define IMFActivate_ActivateObject(p, ...) FFMF_M(IMFActivate, ActivateObject, p, __VA_ARGS__)
#undef IMFActivate_GetString
#define IMFActivate_GetString(p, ...) FFMF_M(IMFActivate, GetString, p, __VA_ARGS__)
#undef IMFTransform_Release
#define IMFTransform_Release(p) FFMF_M0(IMFTransform, Release, p)
#undef IMFTransform_SetInputType
#define IMFTransform_SetInputType(p, ...) FFMF_M(IMFTransform, SetInputType, p, __VA_ARGS__)
#undef IMFTransform_GetOutputAvailableType
#define IMFTransform_GetOutputAvailableType(p, ...) FFMF_M(IMFTransform, GetOutputAvailableType, p, __VA_ARGS__)
#undef IMFTransform_SetOutputType
#define IMFTransform_SetOutputType(p, ...) FFMF_M(IMFTransform, SetOutputType, p, __VA_ARGS__)
#undef IMFTransform_GetOutputStreamInfo
#define IMFTransform_GetOutputStreamInfo(p, ...) FFMF_M(IMFTransform, GetOutputStreamInfo, p, __VA_ARGS__)
#undef IMFTransform_ProcessMessage
#define IMFTransform_ProcessMessage(p, ...) FFMF_M(IMFTransform, ProcessMessage, p, __VA_ARGS__)
#undef IMFTransform_ProcessInput
#define IMFTransform_ProcessInput(p, ...) FFMF_M(IMFTransform, ProcessInput, p, __VA_ARGS__)
#undef IMFTransform_ProcessOutput
#define IMFTransform_ProcessOutput(p, ...) FFMF_M(IMFTransform, ProcessOutput, p, __VA_ARGS__)
#endif
