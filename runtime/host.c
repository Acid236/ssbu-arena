/* Host side of the feasibility demo: loads the SSBU 13.0.4 image at its real
 * address, provides the few imports the lifted code needs, and runs the game's
 * own zstd decompressor (translated to C by recomp.py) on a test file. */
#include <stdio.h>
#include <stdlib.h>
#include <malloc.h>
#include <windows.h>
#include "runtime.h"

#define BASE 0x7100000000ULL
#define IMAGE_SIZE 0x7500000ULL          /* text + rodata + data + bss, rounded up */
#define FILE_OFF 0x1000ULL
#define FILE_IMAGE 0x52a8570ULL          /* bytes of the image stored in the ELF */
#define RELA 0x39c8070ULL
#define RELASZ 0x7ad0d8ULL

void f_7103541ae0(Ctx *c);               /* creates the decompression stream pair */
void f_71039a4040(Ctx *c);               /* ZSTD_decompressStream(zds, out, in)   */
void f_71039a3e70(Ctx *c);               /* ZSTD_freeDStream(zds)                 */

void guest_trap(const char *what, uint64_t addr) {
    fprintf(stderr, "GUEST TRAP: %s (0x%llx)\n", what, (unsigned long long)addr);
    exit(2);
}
void guest_unimpl(uint64_t pc, uint32_t insn, const char *what) {
    fprintf(stderr, "UNIMPLEMENTED INSTRUCTION at 0x%llx: %08x (%s)\n", (unsigned long long)pc, insn, what);
    exit(3);
}
void guest_svc(Ctx *c, uint32_t number) { (void)c; guest_trap("svc", number); }

/* ---- imports the lifted code calls through the PLT */
void imp_memcpy(Ctx *c) { memcpy((void *)c->x[0], (void *)c->x[1], (size_t)c->x[2]); }
void imp_memmove(Ctx *c) { memmove((void *)c->x[0], (void *)c->x[1], (size_t)c->x[2]); }
void imp_memset(Ctx *c) { memset((void *)c->x[0], (int)c->x[1], (size_t)c->x[2]); }
void imp_pthread_mutex_lock(Ctx *c) { c->x[0] = 0; }
void imp_pthread_mutex_unlock(Ctx *c) { c->x[0] = 0; }
void imp_pthread_mutex_destroy(Ctx *c) { c->x[0] = 0; }
void imp_pthread_cond_broadcast(Ctx *c) { c->x[0] = 0; }
void imp_pthread_cond_destroy(Ctx *c) { c->x[0] = 0; }
void imp_pthread_join(Ctx *c) { c->x[0] = 0; }

/* ---- guest functions replaced by host code (the game's allocator entry points) */
static unsigned long long g_allocs, g_alloc_bytes;
void h_memalign(Ctx *c) {
    size_t align = (size_t)c->x[0], size = (size_t)c->x[1];
    if (align < 16) align = 16;
    g_allocs++;
    g_alloc_bytes += size;
    c->x[0] = (uint64_t)_aligned_malloc(size ? size : 1, align);
}
void h_free(Ctx *c) { _aligned_free((void *)c->x[0]); }

static void *read_file(const char *path, size_t *size) {
    FILE *f = fopen(path, "rb");
    if (!f) { fprintf(stderr, "cannot open %s\n", path); exit(1); }
    fseek(f, 0, SEEK_END);
    long n = ftell(f);
    fseek(f, 0, SEEK_SET);
    void *p = malloc((size_t)n + 1);
    if (fread(p, 1, (size_t)n, f) != (size_t)n) { fprintf(stderr, "short read on %s\n", path); exit(1); }
    fclose(f);
    *size = (size_t)n;
    return p;
}

static void load_image(const char *elf) {
    void *mem = VirtualAlloc((void *)BASE, IMAGE_SIZE, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE);
    if (mem != (void *)BASE) { fprintf(stderr, "cannot map guest image at 0x%llx\n", BASE); exit(1); }
    FILE *f = fopen(elf, "rb");
    if (!f) { fprintf(stderr, "cannot open %s\n", elf); exit(1); }
    fseek(f, (long)FILE_OFF, SEEK_SET);
    if (fread(mem, 1, FILE_IMAGE, f) != FILE_IMAGE) { fprintf(stderr, "short read on image\n"); exit(1); }
    fclose(f);
    /* R_AARCH64_RELATIVE: the only relocation type needed for internal pointers */
    unsigned long long applied = 0;
    for (uint64_t i = 0; i < RELASZ / 24; i++) {
        uint64_t off = rd64(BASE + RELA + i * 24), info = rd64(BASE + RELA + i * 24 + 8);
        int64_t addend = (int64_t)rd64(BASE + RELA + i * 24 + 16);
        if (info == 0x403) { wr64(BASE + off, BASE + (uint64_t)addend); applied++; }
    }
    printf("image mapped at 0x%llx, %llu relocations applied\n", BASE, applied);
}

int main(int argc, char **argv) {
    const char *elf = argc > 1 ? argv[1] : "..\\binaries\\13.0.4\\main.elf";
    const char *zst = argc > 2 ? argv[2] : "test.zst";
    const char *raw = argc > 3 ? argv[3] : "test.raw";
    load_image(elf);

    size_t in_size, expect_size;
    uint8_t *in_data = read_file(zst, &in_size);
    uint8_t *expect = read_file(raw, &expect_size);
    uint8_t *out_data = malloc(expect_size + 64);

    static Ctx c;
    size_t stack_size = 8u << 20;
    uint8_t *stack = _aligned_malloc(stack_size, 16);
    c.x[31] = (uint64_t)(stack + stack_size - 64);

    uint64_t pair[2] = {0, 0};                 /* [0] compressor side (unused), [1] ZSTD_DStream* */
    c.x[0] = (uint64_t)pair;
    f_7103541ae0(&c);
    printf("stream create returned %d, dstream = 0x%llx\n", (int)c.x[0], (unsigned long long)pair[1]);
    if ((int)c.x[0] != 0 || pair[1] == 0) return 1;

    uint64_t out_buf[3] = {(uint64_t)out_data, expect_size, 0};   /* dst, size, pos */
    uint64_t in_buf[3] = {(uint64_t)in_data, in_size, 0};         /* src, size, pos */
    LARGE_INTEGER t0, t1, freq;
    QueryPerformanceFrequency(&freq);
    QueryPerformanceCounter(&t0);
    uint64_t ret = 0;
    int calls = 0;
    do {
        c.x[0] = pair[1];
        c.x[1] = (uint64_t)out_buf;
        c.x[2] = (uint64_t)in_buf;
        f_71039a4040(&c);
        ret = c.x[0];
        calls++;
        if (ret >= 0xffffffffffffff89ULL) { printf("zstd error code %lld\n", (long long)ret); return 1; }
    } while (ret != 0 && in_buf[2] < in_buf[1] && calls < 100000);
    QueryPerformanceCounter(&t1);
    double ms = 1000.0 * (double)(t1.QuadPart - t0.QuadPart) / (double)freq.QuadPart;

    c.x[0] = pair[1];
    f_71039a3e70(&c);

    int ok = out_buf[2] == expect_size && memcmp(out_data, expect, expect_size) == 0;
    printf("decompressed %llu -> %llu bytes in %d call(s), %.1f ms (%.0f MB/s)\n",
           (unsigned long long)in_buf[2], (unsigned long long)out_buf[2], calls, ms,
           ms > 0 ? (double)out_buf[2] / 1048576.0 / (ms / 1000.0) : 0.0);
    printf("guest allocations: %llu (%llu bytes)\n", g_allocs, g_alloc_bytes);
    printf("RESULT: %s\n", ok ? "OUTPUT IDENTICAL TO THE ORIGINAL DATA" : "MISMATCH");
    return ok ? 0 : 1;
}
