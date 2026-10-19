/* Linux build: the waveOut subset nnaudio.c uses, on an SDL3 audio stream (plat_posix.c). Buffers are taken in the
 * order written; a buffer is "done" (WHDR_DONE, the CALLBACK_EVENT event set) when SDL has pulled all of it. */
#ifndef PLAT_MMSYSTEM_H
#define PLAT_MMSYSTEM_H
#include "windows.h"
typedef struct HWAVEOUT__ *HWAVEOUT;
typedef HWAVEOUT *LPHWAVEOUT;
typedef struct { WORD wFormatTag, nChannels; DWORD nSamplesPerSec, nAvgBytesPerSec; WORD nBlockAlign, wBitsPerSample, cbSize; } WAVEFORMATEX;
typedef struct wavehdr_tag { LPSTR lpData; DWORD dwBufferLength, dwBytesRecorded; DWORD_PTR dwUser; DWORD dwFlags, dwLoops; struct wavehdr_tag *lpNext; DWORD_PTR reserved; } WAVEHDR;
typedef struct { UINT wType; union { DWORD ms, sample, cb, ticks; struct { BYTE hour, min, sec, frame, fps, dummy, pad[2]; } smpte; struct { DWORD songptrpos; } midi; } u; } MMTIME;
#define WAVE_FORMAT_PCM 1
#define WAVE_MAPPER ((UINT)-1)
#define CALLBACK_NULL 0
#define CALLBACK_EVENT 0x50000
#define MMSYSERR_NOERROR 0
#define MMSYSERR_ERROR 1
#define MMSYSERR_INVALHANDLE 5
#define MMSYSERR_NODRIVER 6
#define WAVERR_STILLPLAYING 33
#define WHDR_DONE 0x1
#define WHDR_PREPARED 0x2
#define WHDR_INQUEUE 0x10
#define TIME_MS 1
#define TIME_SAMPLES 2
#define TIME_BYTES 4
MMRESULT waveOutOpen(HWAVEOUT *out, UINT dev, const WAVEFORMATEX *f, DWORD_PTR cb, DWORD_PTR inst, DWORD flags);
MMRESULT waveOutClose(HWAVEOUT w);
MMRESULT waveOutPrepareHeader(HWAVEOUT w, WAVEHDR *h, UINT size);
MMRESULT waveOutUnprepareHeader(HWAVEOUT w, WAVEHDR *h, UINT size);
MMRESULT waveOutWrite(HWAVEOUT w, WAVEHDR *h, UINT size);
MMRESULT waveOutPause(HWAVEOUT w);
MMRESULT waveOutRestart(HWAVEOUT w);
MMRESULT waveOutReset(HWAVEOUT w);
MMRESULT waveOutGetPosition(HWAVEOUT w, MMTIME *t, UINT size);
MMRESULT waveOutSetVolume(HWAVEOUT w, DWORD vol);
#endif
