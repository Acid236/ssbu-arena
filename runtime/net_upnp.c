/* UPnP-IGD port mapping for online play (Windows NAT traversal COM API: IUPnPNAT -> IStaticPortMappingCollection).
 * UPnP approach after SNO2207/WindowSmash, used with the author's permission. The code is our own.
 *
 * #included by net_relay.c, so everything is static. Needs winsock2.h, windows.h, stdio, string, stdint before it
 * (it includes them itself when compiled alone).
 *
 *   upnp_map_udp(port, lan_ip, desc, ext_ip, n, why, n)   external UDP port -> lan_ip:port; 1 ok, 0 failed (why)
 *   upnp_unmap_udp(port)                                   removes that mapping (call at exit)
 *   upnp_probe(why, n)                                     READ ONLY: 1 if an IGD answers (why: existing mappings)
 *
 * Every COM call runs on a short-lived worker thread (its own CoInitializeEx) and the caller waits at most
 * UPNP_WAIT_MS, so a silent router can never freeze the game. A worker that outlives the wait is abandoned. */
#ifndef NET_UPNP_C
#define NET_UPNP_C

#ifndef _WIN32_DCOM
#define _WIN32_DCOM
#endif
#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#define COBJMACROS
#include <ole2.h>
#include <oleauto.h>
#include <natupnp.h>

#pragma comment(lib, "ole32.lib")
#pragma comment(lib, "oleaut32.lib")

#define UPNP_WAIT_MS 6000
#define UPNP_UNMAP_WAIT_MS 4000

/* own copies of the two GUIDs, so no uuid.lib is needed */
static const GUID upnp_clsid_nat = { 0xAE1E00AA, 0x3FD5, 0x403C, { 0x8A, 0x27, 0x2B, 0xBD, 0xC3, 0x0C, 0xD0, 0xE1 } };
static const GUID upnp_iid_nat   = { 0xB171C812, 0xCC76, 0x485A, { 0x94, 0xD8, 0xB6, 0xB3, 0xA2, 0x79, 0x4E, 0x99 } };

enum { UPNP_OP_MAP = 1, UPNP_OP_UNMAP, UPNP_OP_PROBE };

typedef struct upnp_job {
    volatile LONG refs;            /* waiter + worker; the last one frees */
    HANDLE done;                   /* manual-reset event, set by the worker when finished */
    int op;
    uint16_t port;
    char lan[16];
    char desc[64];
    int ok;                        /* result */
    char ext[64];
    char why[96];
} upnp_job;

static void upnp_job_release(upnp_job *j)
{
    if (InterlockedDecrement(&j->refs) == 0) {
        if (j->done) CloseHandle(j->done);
        free(j);
    }
}

static void upnp_fail(upnp_job *j, const char *why)
{
    j->ok = 0;
    snprintf(j->why, sizeof j->why, "%s", why);
}

static DWORD WINAPI upnp_worker(LPVOID arg)
{
    upnp_job *j = (upnp_job *)arg;
    HRESULT hr = CoInitializeEx(NULL, COINIT_MULTITHREADED);
    int com = SUCCEEDED(hr);
    IUPnPNAT *nat = NULL;
    IStaticPortMappingCollection *col = NULL;

    if (!com && hr != RPC_E_CHANGED_MODE) { upnp_fail(j, "COM could not start"); goto out; }
    hr = CoCreateInstance(&upnp_clsid_nat, NULL, CLSCTX_ALL, &upnp_iid_nat, (void **)&nat);
    if (FAILED(hr) || !nat) { upnp_fail(j, "no UPnP service on this PC"); goto out; }
    hr = IUPnPNAT_get_StaticPortMappingCollection(nat, &col);
    if (FAILED(hr) || !col) { upnp_fail(j, "no UPnP router answered"); goto out; }

    if (j->op == UPNP_OP_PROBE) {
        long n = 0;
        if (SUCCEEDED(IStaticPortMappingCollection_get_Count(col, &n))) {
            j->ok = 1;
            snprintf(j->why, sizeof j->why, "UPnP router answered, %ld existing mapping(s)", n);
        } else {
            j->ok = 1;
            snprintf(j->why, sizeof j->why, "UPnP router answered, mapping count not readable");
        }
    } else if (j->op == UPNP_OP_UNMAP) {
        BSTR proto = SysAllocString(L"UDP");
        hr = proto ? IStaticPortMappingCollection_Remove(col, (long)j->port, proto) : E_OUTOFMEMORY;
        SysFreeString(proto);
        if (SUCCEEDED(hr)) { j->ok = 1; snprintf(j->why, sizeof j->why, "mapping removed"); }
        else upnp_fail(j, "router refused to remove the mapping");
    } else {
        wchar_t wlan[16], wdesc[64];
        BSTR proto, client, desc;
        IStaticPortMapping *map = NULL;
        MultiByteToWideChar(CP_ACP, 0, j->lan, -1, wlan, 16);
        MultiByteToWideChar(CP_UTF8, 0, j->desc, -1, wdesc, 64);
        proto = SysAllocString(L"UDP");
        client = SysAllocString(wlan);
        desc = SysAllocString(wdesc);
        if (!proto || !client || !desc) hr = E_OUTOFMEMORY;
        else {
            /* a stale mapping of ours from a crashed run would make Add fail: drop it first (ignore the result) */
            IStaticPortMappingCollection_Remove(col, (long)j->port, proto);
            hr = IStaticPortMappingCollection_Add(col, (long)j->port, proto, (long)j->port, client, VARIANT_TRUE, desc, &map);
        }
        SysFreeString(proto); SysFreeString(client); SysFreeString(desc);
        if (FAILED(hr) || !map) {
            upnp_fail(j, "router refused the mapping (port in use?)");
        } else {
            BSTR ext = NULL;
            j->ok = 1;
            snprintf(j->why, sizeof j->why, "mapped");
            if (SUCCEEDED(IStaticPortMapping_get_ExternalIPAddress(map, &ext)) && ext) {
                WideCharToMultiByte(CP_ACP, 0, ext, -1, j->ext, (int)sizeof j->ext, NULL, NULL);
                j->ext[sizeof j->ext - 1] = 0;
            }
            if (ext) SysFreeString(ext);
        }
        if (map) IStaticPortMapping_Release(map);
    }
out:
    if (col) IStaticPortMappingCollection_Release(col);
    if (nat) IUPnPNAT_Release(nat);
    if (com) CoUninitialize();
    SetEvent(j->done);
    upnp_job_release(j);
    return 0;
}

/* runs one operation; returns the finished job (caller releases it) or NULL on timeout / start failure */
static upnp_job *upnp_run(upnp_job *j, DWORD wait_ms)
{
    HANDLE th;
    j->refs = 2;
    j->done = CreateEventA(NULL, TRUE, FALSE, NULL);
    th = j->done ? CreateThread(NULL, 0, upnp_worker, j, 0, NULL) : NULL;
    if (!th) {
        if (j->done) CloseHandle(j->done);
        j->done = NULL;
        free(j);
        return NULL;
    }
    CloseHandle(th);
    if (WaitForSingleObject(j->done, wait_ms) == WAIT_OBJECT_0) return j;
    upnp_job_release(j);           /* abandoned: the worker frees it when (if) it ends */
    return NULL;
}

static void upnp_copy(char *dst, size_t n, const char *src)
{
    if (dst && n) snprintf(dst, n, "%s", src);
}

static int upnp_finish(upnp_job *j, char *ext_ip, size_t ext_n, char *why, size_t why_n)
{
    int ok;
    if (!j) { upnp_copy(why, why_n, "no UPnP router answered (timeout)"); return 0; }
    ok = j->ok;
    upnp_copy(why, why_n, j->why);
    if (ok && ext_ip) upnp_copy(ext_ip, ext_n, j->ext);
    upnp_job_release(j);
    return ok;
}

static int upnp_map_udp(uint16_t port, uint32_t lan_ip_host_order, const char *desc,
                        char *ext_ip, size_t ext_n, char *why, size_t why_n)
{
    upnp_job *j = (upnp_job *)calloc(1, sizeof *j);
    if (ext_ip && ext_n) ext_ip[0] = 0;
    if (!j) { upnp_copy(why, why_n, "out of memory"); return 0; }
    j->op = UPNP_OP_MAP;
    j->port = port;
    snprintf(j->lan, sizeof j->lan, "%u.%u.%u.%u", (unsigned)(lan_ip_host_order >> 24) & 255,
             (unsigned)(lan_ip_host_order >> 16) & 255, (unsigned)(lan_ip_host_order >> 8) & 255,
             (unsigned)lan_ip_host_order & 255);
    snprintf(j->desc, sizeof j->desc, "%s", desc ? desc : "SSBU online");
    return upnp_finish(upnp_run(j, UPNP_WAIT_MS), ext_ip, ext_n, why, why_n);
}

static void upnp_unmap_udp(uint16_t port)
{
    upnp_job *j = (upnp_job *)calloc(1, sizeof *j);
    if (!j) return;
    j->op = UPNP_OP_UNMAP;
    j->port = port;
    upnp_finish(upnp_run(j, UPNP_UNMAP_WAIT_MS), NULL, 0, NULL, 0);
}

static int upnp_probe(char *why, size_t why_n)
{
    upnp_job *j = (upnp_job *)calloc(1, sizeof *j);
    if (!j) { upnp_copy(why, why_n, "out of memory"); return 0; }
    j->op = UPNP_OP_PROBE;
    return upnp_finish(upnp_run(j, UPNP_WAIT_MS), NULL, 0, why, why_n);
}

#ifdef UPNP_MAIN
/* test: the probe is read only. The mapping calls are compiled but only run with the flag --really-map, which the
 * test run does NOT use (it changes the router configuration and needs the owner's permission). */
int main(int argc, char **argv)
{
    char why[128] = "", ext[64] = "";
    int ok;
    if (argc > 3 && !strcmp(argv[1], "--really-map")) {
        ok = upnp_map_udp((uint16_t)atoi(argv[2]), 0, argv[3], ext, sizeof ext, why, sizeof why);
        printf("map: %d ext=%s why=%s\n", ok, ext, why);
        upnp_unmap_udp((uint16_t)atoi(argv[2]));
        return !ok;
    }
    ok = upnp_probe(why, sizeof why);
    printf("probe: %d (%s)\n", ok, why);
    return 0;
}
#endif
#endif /* NET_UPNP_C */
