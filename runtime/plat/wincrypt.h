/* Linux build: the CryptoAPI subset nnmisc.c uses (random bytes, SHA-1, MD5, SHA-256 hashes), on getrandom and OpenSSL. */
#ifndef PLAT_WINCRYPT_H
#define PLAT_WINCRYPT_H
#include "windows.h"
typedef ULONG_PTR HCRYPTPROV;
typedef ULONG_PTR HCRYPTHASH;
typedef ULONG_PTR HCRYPTKEY;
typedef unsigned int ALG_ID;
#define PROV_RSA_FULL 1
#define PROV_RSA_AES 24
#define CRYPT_VERIFYCONTEXT 0xF0000000u
#define CALG_MD5 0x8003
#define CALG_SHA1 0x8004
#define CALG_SHA_256 0x800c
#define HP_HASHVAL 2
#define HP_HASHSIZE 4
BOOL CryptAcquireContextA(HCRYPTPROV *prov, LPCSTR container, LPCSTR provider, DWORD type, DWORD flags);
BOOL CryptReleaseContext(HCRYPTPROV prov, DWORD flags);
BOOL CryptGenRandom(HCRYPTPROV prov, DWORD n, BYTE *buf);
BOOL CryptCreateHash(HCRYPTPROV prov, ALG_ID alg, HCRYPTKEY key, DWORD flags, HCRYPTHASH *out);
BOOL CryptHashData(HCRYPTHASH h, const BYTE *data, DWORD n, DWORD flags);
BOOL CryptGetHashParam(HCRYPTHASH h, DWORD param, BYTE *out, DWORD *n, DWORD flags);
BOOL CryptDestroyHash(HCRYPTHASH h);
#endif
