/* tex_test.c - tests and tools for tex_decode.c
 *
 *   tex_test.exe self                         self-checks without game data (exit code = failures)
 *   tex_test.exe scan <scan.txt>              storage sizes against the game's nutexb footers (tex_samples\scan.txt)
 *   tex_test.exe nutexb <file> <out.png> [layer] [level]   decode a packaged game texture (footer -> layout) to PNG
 *   tex_test.exe decode <raw> <w> <h> <format> <bhlog2> <out.png>   decode a raw block-linear level-0 dump
 *   tex_test.exe gl                           compare the BCn / ASTC decoders with the GL driver's (random blocks)
 *   tex_test.exe bench                        throughput of the decoders
 *
 * build: C:\llvm-8.0.0\bin\clang.exe -O1 -o tex_test.exe tex_test.c tex_decode.c -lopengl32 -lgdi32 -luser32 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <windows.h>
#include <GL/gl.h>
#include "tex_decode.h"

/* test aids exported by tex_decode.c, not part of the API in tex_decode.h */
int tex_astc_partition_reference(int seed, int x, int y, int count, int small_block);   /* the selection function as written in the specification */
extern int tex_astc_test_full_bise;                                                     /* see cmd_astccmp */

static int g_fail, g_pass;
#define CHECK(cond, ...) do { if (cond) g_pass++; else { g_fail++; printf("FAIL %s:%d: ", __FILE__, __LINE__); printf(__VA_ARGS__); printf("\n"); } } while (0)

static uint64_t g_rng = 0x9E3779B97F4A7C15ULL;
static uint32_t rnd(void) { g_rng ^= g_rng << 13; g_rng ^= g_rng >> 7; g_rng ^= g_rng << 17; return (uint32_t)(g_rng >> 11); }
static void rnd_fill(uint8_t *p, size_t n) { size_t i; for (i = 0; i < n; i++) p[i] = (uint8_t)rnd(); }

static uint8_t *read_file(const char *path, size_t *len) {
    FILE *fp = fopen(path, "rb");
    uint8_t *d;
    long n;
    if (!fp) return NULL;
    fseek(fp, 0, SEEK_END); n = ftell(fp); fseek(fp, 0, SEEK_SET);
    d = (uint8_t *)malloc((size_t)n + 1);
    if (fread(d, 1, (size_t)n, fp) != (size_t)n) { fclose(fp); free(d); return NULL; }
    fclose(fp);
    *len = (size_t)n;
    return d;
}

static double now_s(void) { LARGE_INTEGER f, c; QueryPerformanceFrequency(&f); QueryPerformanceCounter(&c); return (double)c.QuadPart / (double)f.QuadPart; }

/* ---------------------------------------------------------------- bit writer for hand-made blocks */
typedef struct { uint8_t b[16]; int pos; } BW;
static void bw_put(BW *w, uint32_t v, int n) { int i; for (i = 0; i < n; i++, w->pos++) if ((v >> i) & 1) w->b[w->pos >> 3] |= (uint8_t)(1 << (w->pos & 7)); }
static void bw_set(BW *w, int pos, uint32_t v, int n) { int i; for (i = 0; i < n; i++) if ((v >> i) & 1) w->b[(pos + i) >> 3] |= (uint8_t)(1 << ((pos + i) & 7)); }
/* ASTC weight bit i goes to block bit 127 - i */
static void bw_weight(BW *w, int *wpos, uint32_t v, int n) { int i; for (i = 0; i < n; i++, (*wpos)++) if ((v >> i) & 1) { int bp = 127 - *wpos; w->b[bp >> 3] |= (uint8_t)(1 << (bp & 7)); } }

/* ---------------------------------------------------------------- nutexb */
typedef struct { int w, h, d, fmt, mips, layers; uint32_t dsize; uint32_t mip_sizes[16]; char name[64]; } Nutexb;
static int nutexb_parse(const uint8_t *d, size_t n, Nutexb *f) {
    const uint8_t *b;
    int i;
    if (n < 0xB0 || memcmp(d + n - 8, " XET", 4) || memcmp(d + n - 0x70, " XNT", 4)) return -1;
    b = d + n - 0xB0;
    for (i = 0; i < 16; i++) memcpy(&f->mip_sizes[i], b + i * 4, 4);
    memcpy(f->name, b + 0x44, 63); f->name[63] = 0;
    memcpy(&f->w, b + 0x84, 4); memcpy(&f->h, b + 0x88, 4); memcpy(&f->d, b + 0x8C, 4);
    f->fmt = b[0x90];
    memcpy(&f->mips, b + 0x98, 4); memcpy(&f->layers, b + 0xA0, 4); memcpy(&f->dsize, b + 0xA4, 4);
    return 0;
}
static int nutexb_to_nvn(int fmt) {
    switch (fmt) {
    case 0x00: return TEX_FMT_RGBA8; case 0x05: return TEX_FMT_RGBA8_SRGB; case 0x34: return TEX_FMT_RGBA32F; case 0x50: return TEX_FMT_BGRA8; case 0x55: return TEX_FMT_BGRA8_SRGB;
    case 0x80: return TEX_FMT_RGBA_DXT1; case 0x85: return TEX_FMT_RGBA_DXT1_SRGB; case 0x90: return TEX_FMT_RGBA_DXT3; case 0x95: return TEX_FMT_RGBA_DXT3_SRGB;
    case 0xA0: return TEX_FMT_RGBA_DXT5; case 0xA5: return TEX_FMT_RGBA_DXT5_SRGB; case 0xB0: return TEX_FMT_RGTC1_UNORM; case 0xB5: return TEX_FMT_RGTC1_SNORM;
    case 0xC0: return TEX_FMT_RGTC2_UNORM; case 0xC5: return TEX_FMT_RGTC2_SNORM; case 0xD7: return TEX_FMT_BPTC_UFLOAT; case 0xD8: return TEX_FMT_BPTC_SFLOAT;
    case 0xE0: return TEX_FMT_BPTC_UNORM; case 0xE5: return TEX_FMT_BPTC_UNORM_SRGB;
    }
    return -1;
}

/* layout of a nutexb: layers 6 -> cubemap, depth > 1 -> 3D, else 2D */
static int nutexb_layout(TexLayout *L, int fmt, int w, int h, int d, int mips, int layers) {
    int nf = nutexb_to_nvn(fmt);
    if (nf < 0) return -1;
    return tex_layout(L, layers == 6 ? TEX_TARGET_CUBEMAP : d > 1 ? TEX_TARGET_3D : layers > 1 ? TEX_TARGET_2D_ARRAY : TEX_TARGET_2D, nf, w, h, layers == 6 ? 1 : d > 1 ? d : layers, mips, 0, 0, -1);
}

/* ---------------------------------------------------------------- self tests */
/* suyu's pdep formulation of the GOB swizzle as an independent oracle */
static uint32_t pdep(uint32_t mask, uint32_t value) { uint32_t r = 0, bit; for (bit = 1; mask; bit += bit) { if (value & bit) r |= mask & (~mask + 1); mask &= mask - 1; } return r; }
static size_t oracle_offset(int x, int y, int z, int wbytes, int hrows, int bh, int bd) {
    uint32_t gobs_in_x = (uint32_t)((wbytes + 63) / 64), block_size = gobs_in_x << (9 + bh + bd), slice_size = (uint32_t)((hrows + (8 << bh) - 1) >> (3 + bh)) * block_size;
    uint32_t off_z = ((uint32_t)z >> bd) * slice_size + (((uint32_t)z & ((1u << bd) - 1)) << (9 + bh));
    uint32_t block_y = (uint32_t)y >> 3, off_y = (block_y >> bh) * block_size + ((block_y & ((1u << bh) - 1)) << 9);
    uint32_t off_x = ((uint32_t)x >> 6) << (9 + bh + bd);
    return off_z + off_y + off_x + (pdep(0x12F, (uint32_t)x) | pdep(0x0D0, (uint32_t)y));
}

static void test_formats(void) {
    int nf, n = 0;
    for (nf = 1; nf < TEX_FMT_COUNT; nf++) {
        const TexFormat *f = tex_format(nf);
        if (!f) continue;
        n++;
        CHECK(f->bpb > 0 && f->bw > 0 && f->bh > 0, "format 0x%x has no size", nf);
        CHECK(f->gl_internal != 0, "format 0x%x (%s) has no GL internal format", nf, f->name);
        if (f->compressed) CHECK(f->codec != 0, "compressed format 0x%x without codec", nf);
    }
    CHECK(n == 0x9C, "%d formats described, expected 156", n);
    CHECK(tex_format(0x25)->bpb == 4 && tex_format(0x4E)->bpb == 16 && tex_format(0x49)->bpb == 8 && tex_format(0x7D)->bw == 6 && tex_format(0x7D)->bh == 6, "spot check of sizes");
    CHECK(tex_format(0x16)->bpb == 8 && tex_format(0x22)->bpb == 12 && tex_format(0x2E)->bpb == 16 && tex_format(0x11)->bpb == 4, "RG32F/RGB32F/RGBA32F/RG16F sizes");
    CHECK(tex_format(0x94)->srgb && tex_format(0x94)->bw == 12 && tex_format(0x94)->sw_decode, "ASTC 12x12 sRGB");
    CHECK(tex_format(0x9D) == NULL && tex_format(0) == NULL, "out of range");
    printf("formats: %d described\n", n);
}

static void test_swizzle(void) {
    int it, n_oracle = 0;
    uint8_t *lin = (uint8_t *)malloc(1 << 20), *bl = (uint8_t *)malloc(1 << 21), *back = (uint8_t *)malloc(1 << 20);
    static const int bpbs[6] = {1, 2, 4, 8, 12, 16};
    for (it = 0; it < 300; it++) {
        int bpb = bpbs[rnd() % 6], wb = 1 + (int)(rnd() % 300), hb = 1 + (int)(rnd() % 200), d = 1 + (int)(rnd() % 4), bh = (int)(rnd() % 5), bd = d > 1 ? (int)(rnd() % 3) : 0;
        int wbytes = wb * bpb, k;
        size_t lsize = (size_t)wbytes * hb * d, bsize = tex_bl_size(wbytes, hb, d, bh, bd);
        if (lsize > (1 << 20) || bsize > (1 << 21)) continue;
        rnd_fill(lin, lsize);
        memset(bl, 0xAA, bsize);
        tex_linear_to_bl(bl, lin, wbytes, hb, d, bh, bd);
        memset(back, 0, lsize);
        tex_bl_to_linear(back, bl, wbytes, hb, d, bh, bd);
        CHECK(!memcmp(lin, back, lsize), "swizzle round trip %dx%dx%d bpb %d bh %d bd %d", wb, hb, d, bpb, bh, bd);
        for (k = 0; k < 64; k++) {
            int x = (int)(rnd() % (uint32_t)wbytes), y = (int)(rnd() % (uint32_t)hb), z = (int)(rnd() % (uint32_t)d);
            size_t o = tex_bl_offset(x, y, z, wbytes, hb, bh, bd), o2 = oracle_offset(x, y, z, wbytes, hb, bh, bd);
            if (o != o2 || o >= bsize || bl[o] != lin[((size_t)z * hb + y) * wbytes + x]) {
                CHECK(0, "offset mismatch at (%d,%d,%d) %dx%dx%d bh %d bd %d: %zu oracle %zu", x, y, z, wbytes, hb, d, bh, bd, o, o2);
                break;
            }
            n_oracle++;
        }
    }
    free(lin); free(bl); free(back);
    printf("swizzle: %d round trips, %d offsets against the pdep oracle\n", g_pass, n_oracle);
}

/* the 40 packaged-texture layouts logged by the backend: {height, format block height, expected log2} */
static void test_block_height_rule(void) {
    static const int cases[][3] = {{285, 4, 3}, {56, 4, 1}, {16, 4, 0}, {108, 4, 2}, {3, 4, 0}, {73, 4, 1}, {200, 4, 3}, {147, 4, 2}, {128, 4, 2}, {64, 4, 1}, {512, 4, 4}, {256, 4, 3}, {60, 4, 1}, {28, 4, 0}};
    size_t i;
    for (i = 0; i < sizeof cases / sizeof cases[0]; i++) {
        int hb = (cases[i][0] + cases[i][1] - 1) / cases[i][1];
        CHECK(tex_rule_block_height_log2(hb) == cases[i][2], "block height rule for height %d: %d expected %d", cases[i][0], tex_rule_block_height_log2(hb), cases[i][2]);
    }
    /* level 0 is never reduced by the mip rule (the two rules agree) */
    for (i = 1; i < 2000; i++) CHECK(tex_rule_mip_block_height_log2((int)i, tex_rule_block_height_log2((int)i)) == tex_rule_block_height_log2((int)i), "mip rule changes level 0 at %zu", i);
}

/* storage sizes of game textures (from tex_samples\scan.txt footers): {nutexb fmt, w, h, d, mips, layers, data size} */
static void test_storage_sizes(void) {
    static const int cases[][7] = {
        {0xE5, 1024, 512, 1, 11, 1, 701952}, {0xE5, 24, 8, 1, 5, 1, 3072}, {0xE0, 512, 256, 1, 10, 1, 177664}, {0xE0, 256, 256, 1, 9, 1, 89600},
        {0xE0, 512, 1024, 1, 11, 1, 701440}, {0xA0, 256, 128, 1, 9, 1, 46592}, {0x05, 64, 32, 1, 7, 1, 12800}, {0xE0, 512, 512, 1, 10, 1, 351744},
        {0xE0, 128, 256, 1, 9, 1, 46080}, {0x00, 16, 16, 16, 1, 1, 16384}, {0xD7, 64, 64, 1, 7, 6, 49152}, {0xD7, 512, 512, 1, 10, 6, 2113536},
        {0xD7, 16, 16, 1, 5, 6, 15360}, {0xE0, 1024, 1024, 1, 11, 1, 1400320}, {0x85, 512, 512, 1, 10, 1, 177152}, {0x85, 256, 128, 1, 9, 1, 24576},
        {0xA5, 1024, 256, 1, 11, 1, 353792}, {0x85, 512, 512, 1, 1, 1, 131072}, {0x80, 256, 256, 1, 9, 1, 46080}, {0x34, 32, 4, 1, 1, 1, 4096},
        {0x00, 512, 256, 1, 1, 1, 524288}};
    size_t i;
    for (i = 0; i < sizeof cases / sizeof cases[0]; i++) {
        TexLayout L;
        nutexb_layout(&L, cases[i][0], cases[i][1], cases[i][2], cases[i][3], cases[i][4], cases[i][5]);
        CHECK(L.data_size == (size_t)cases[i][6] && L.size >= L.data_size && L.size - L.data_size < L.alignment, "storage size fmt %02x %dx%dx%d mips %d layers %d: %zu, game %d", cases[i][0], cases[i][1], cases[i][2], cases[i][3], cases[i][4], cases[i][5], L.data_size, cases[i][6]);
    }
    printf("storage sizes: %zu game textures checked\n", i);
}

static void test_bc1_5(void) {
    uint8_t blk[16], out[16 * 4];
    int i;
    /* BC1 solid colour: c0 = c1 = 0xF800 (red), indices 0 -> (255,0,0,255) */
    memset(blk, 0, 8); blk[0] = 0x00; blk[1] = 0xF8; blk[2] = 0x00; blk[3] = 0xF8;
    tex_decode_block_rgba8(TEX_FMT_RGBA_DXT1, blk, out, 16);
    for (i = 0; i < 16; i++) CHECK(out[i * 4] == 255 && out[i * 4 + 1] == 0 && out[i * 4 + 2] == 0 && out[i * 4 + 3] == 255, "BC1 solid red pixel %d = %d,%d,%d,%d", i, out[i * 4], out[i * 4 + 1], out[i * 4 + 2], out[i * 4 + 3]);
    /* BC1 two colours: c0 = white (0xFFFF), c1 = black, indices 0,1,2,3 repeating: 4-colour mode */
    blk[0] = 0xFF; blk[1] = 0xFF; blk[2] = 0; blk[3] = 0; blk[4] = blk[5] = blk[6] = blk[7] = 0xE4;   /* 11 10 01 00 */
    tex_decode_block_rgba8(TEX_FMT_RGBA_DXT1, blk, out, 16);
    for (i = 0; i < 16; i++) {
        static const int e[4] = {255, 0, 170, 85};
        CHECK(out[i * 4] == e[i & 3] && out[i * 4 + 1] == e[i & 3] && out[i * 4 + 2] == e[i & 3] && out[i * 4 + 3] == 255, "BC1 4-colour pixel %d = %d expected %d", i, out[i * 4], e[i & 3]);
    }
    /* BC1 3-colour mode (c0 <= c1): index 3 -> transparent black with RGBA_DXT1, opaque black with RGB_DXT1 */
    blk[0] = 0; blk[1] = 0; blk[2] = 0xFF; blk[3] = 0xFF;
    tex_decode_block_rgba8(TEX_FMT_RGBA_DXT1, blk, out, 16);
    CHECK(out[0] == 0 && out[4] == 255 && out[8] == 127 && out[12] == 0 && out[15] == 0 && out[11] == 255, "BC1 3-colour: %d %d %d %d alpha %d", out[0], out[4], out[8], out[12], out[15]);
    tex_decode_block_rgba8(TEX_FMT_RGB_DXT1, blk, out, 16);
    CHECK(out[15] == 255, "RGB_DXT1 3-colour alpha %d", out[15]);
    /* BC2: explicit alpha nibbles */
    memset(blk, 0, 16); for (i = 0; i < 8; i++) blk[i] = (uint8_t)(i * 0x22 + 0x10);       /* alpha nibbles 0,1,2,3,... */
    blk[8] = 0xFF; blk[9] = 0xFF;
    tex_decode_block_rgba8(TEX_FMT_RGBA_DXT3, blk, out, 16);
    CHECK(out[3] == 0x00 && out[7] == 0x11 && out[11] == 0x22 && out[15] == 0x33 && out[0] == 255, "BC2 alpha %d %d %d %d colour %d", out[3], out[7], out[11], out[15], out[0]);
    /* BC4 ramp: a0 = 255, a1 = 0, indices 0..7 -> 255, 0, 219, 182, 146, 109, 73, 36 */
    memset(blk, 0, 8); blk[0] = 255; blk[1] = 0;
    { uint64_t idx = 0; for (i = 0; i < 16; i++) idx |= (uint64_t)(i & 7) << (i * 3); for (i = 0; i < 6; i++) blk[2 + i] = (uint8_t)(idx >> (i * 8)); }
    tex_decode_block_rgba8(TEX_FMT_RGTC1_UNORM, blk, out, 16);
    { static const int e[8] = {255, 0, 219, 182, 146, 109, 73, 36};
      for (i = 0; i < 16; i++) CHECK(out[i * 4] == e[i & 7] && out[i * 4 + 1] == 0 && out[i * 4 + 3] == 255, "BC4 ramp pixel %d = %d expected %d", i, out[i * 4], e[i & 7]); }
    /* BC4 6-value mode: a0 = 0, a1 = 100: 0, 100, 20, 40, 60, 80, 0, 255 */
    blk[0] = 0; blk[1] = 100;
    tex_decode_block_rgba8(TEX_FMT_RGTC1_UNORM, blk, out, 16);
    { static const int e[8] = {0, 100, 20, 40, 60, 80, 0, 255};
      for (i = 0; i < 8; i++) CHECK(out[i * 4] == e[i], "BC4 6-value pixel %d = %d expected %d", i, out[i * 4], e[i]); }
    /* BC4 snorm: a0 = 127, a1 = -127, index 1 -> -1.0 -> 0, index 0 -> 1.0 -> 255 */
    blk[0] = 127; blk[1] = (uint8_t)-127;
    tex_decode_block_rgba8(TEX_FMT_RGTC1_SNORM, blk, out, 16);
    CHECK(out[0] == 255 && out[4] == 0 && out[1] == 128, "BC4 snorm %d %d (G %d)", out[0], out[4], out[1]);
    { float fo[64]; tex_decode_rgba32f(TEX_FMT_RGTC1_SNORM, blk, 4, 4, fo); CHECK(fo[0] == 1.0f && fo[4] == -1.0f, "BC4 snorm float %f %f", fo[0], fo[4]); }
    /* BC5: red ramp in the first half, green = a0 = 50 solid in the second */
    memcpy(blk + 8, blk, 8); blk[0] = 255; blk[1] = 0; blk[8] = 50; blk[9] = 50; memset(blk + 10, 0, 6);
    tex_decode_block_rgba8(TEX_FMT_RGTC2_UNORM, blk, out, 16);
    CHECK(out[0] == 255 && out[4] == 0 && out[8] == 219 && out[1] == 50 && out[5] == 50 && out[2] == 0 && out[3] == 255, "BC5 %d %d %d / %d %d / %d %d", out[0], out[4], out[8], out[1], out[5], out[2], out[3]);
    /* BC3: alpha ramp + white colour */
    memset(blk, 0, 16); blk[0] = 255; blk[1] = 0; { uint64_t idx = 0; for (i = 0; i < 16; i++) idx |= (uint64_t)(i & 7) << (i * 3); for (i = 0; i < 6; i++) blk[2 + i] = (uint8_t)(idx >> (i * 8)); }
    blk[8] = blk[9] = 0xFF;
    tex_decode_block_rgba8(TEX_FMT_RGBA_DXT5, blk, out, 16);
    CHECK(out[0] == 255 && out[3] == 255 && out[7] == 0 && out[11] == 219, "BC3 %d a %d %d %d", out[0], out[3], out[7], out[11]);
}

static void test_bc7(void) {
    /* mode 6: 1 subset, 7-bit RGBA endpoints + p-bits, 4-bit indices */
    BW w;
    uint8_t out[64];
    int i;
    memset(&w, 0, sizeof w);
    bw_put(&w, 0x40, 7);                      /* mode 6: six zeros then a one */
    bw_put(&w, 0, 7); bw_put(&w, 127, 7);     /* R0 = 0, R1 = 127 */
    bw_put(&w, 0, 7); bw_put(&w, 127, 7);     /* G */
    bw_put(&w, 0, 7); bw_put(&w, 127, 7);     /* B */
    bw_put(&w, 127, 7); bw_put(&w, 127, 7);   /* A */
    bw_put(&w, 0, 1); bw_put(&w, 1, 1);       /* p-bits: e0 -> 0, e1 -> 255 */
    bw_put(&w, 0, 3);                         /* index 0 (anchor, 3 bits) = 0 */
    for (i = 1; i < 16; i++) bw_put(&w, (uint32_t)i, 4);
    tex_decode_block_rgba8(TEX_FMT_BPTC_UNORM, w.b, out, 16);
    { static const int w4[16] = {0, 4, 9, 13, 17, 21, 26, 30, 34, 38, 43, 47, 51, 55, 60, 64};
      for (i = 0; i < 16; i++) {
          int e = (255 * w4[i] + 32) >> 6, ea = (254 * (64 - w4[i]) + 255 * w4[i] + 32) >> 6;
          CHECK(out[i * 4] == e && out[i * 4 + 1] == e && out[i * 4 + 2] == e && out[i * 4 + 3] == ea, "BC7 mode 6 pixel %d = %d,%d,%d,%d expected %d", i, out[i * 4], out[i * 4 + 1], out[i * 4 + 2], out[i * 4 + 3], e);
      } }
    /* mode 5: rotation 1 swaps R and A: 7-bit colour (100, 50, 25) -> (201, 100, 50), alpha 30 -> output (30, 100, 50, 201) */
    memset(&w, 0, sizeof w);
    bw_put(&w, 0x20, 6);                      /* mode 5 */
    bw_put(&w, 1, 2);                         /* rotation 1 */
    bw_put(&w, 100, 7); bw_put(&w, 100, 7); bw_put(&w, 50, 7); bw_put(&w, 50, 7); bw_put(&w, 25, 7); bw_put(&w, 25, 7);
    bw_put(&w, 30, 8); bw_put(&w, 30, 8);
    tex_decode_block_rgba8(TEX_FMT_BPTC_UNORM, w.b, out, 16);
    CHECK(out[0] == 30 && out[1] == 100 && out[2] == 50 && out[3] == 201, "BC7 mode 5 rotation: %d %d %d %d (expected 30 100 50 201)", out[0], out[1], out[2], out[3]);
    /* mode 8 (reserved: all mode bits zero) -> zeros */
    memset(&w, 0, sizeof w);
    tex_decode_block_rgba8(TEX_FMT_BPTC_UNORM, w.b, out, 16);
    CHECK(out[0] == 0 && out[3] == 0, "BC7 reserved mode");
}

static void test_bc6h(void) {
    BW w;
    float out[64];
    int i;
    /* mode 11 (00011): one region, 10-bit endpoints, 4-bit indices, unsigned: e0 = 0, e1 = 1023 (-> 0xFFFF) */
    memset(&w, 0, sizeof w);
    bw_put(&w, 0x03, 5);
    bw_put(&w, 0, 10); bw_put(&w, 0, 10); bw_put(&w, 0, 10);
    bw_put(&w, 1023, 10); bw_put(&w, 1023, 10); bw_put(&w, 1023, 10);
    bw_put(&w, 0, 3);
    for (i = 1; i < 16; i++) bw_put(&w, (uint32_t)i, 4);
    tex_decode_rgba32f(TEX_FMT_BPTC_UFLOAT, w.b, 4, 4, out);
    { static const int w4[16] = {0, 4, 9, 13, 17, 21, 26, 30, 34, 38, 43, 47, 51, 55, 60, 64};
      for (i = 0; i < 16; i++) {
          int v = (0xFFFF * w4[i] + 32) >> 6;
          float e = tex_half_to_float((uint16_t)((v * 31) >> 6));
          CHECK(out[i * 4] == e && out[i * 4 + 1] == e && out[i * 4 + 2] == e && out[i * 4 + 3] == 1.0f, "BC6H mode 11 pixel %d = %g expected %g", i, out[i * 4], e);
      } }
    CHECK(out[15 * 4] == 65504.0f, "BC6H max = %g", out[15 * 4]);
    /* signed, mode 11: e0 = -512 (sign-extended 10-bit 0x200), e1 = 511 */
    memset(&w, 0, sizeof w);
    bw_put(&w, 0x03, 5);
    bw_put(&w, 0x200, 10); bw_put(&w, 0x200, 10); bw_put(&w, 0x200, 10);
    bw_put(&w, 511, 10); bw_put(&w, 511, 10); bw_put(&w, 511, 10);
    bw_put(&w, 0, 3); for (i = 1; i < 16; i++) bw_put(&w, 15, 4);
    tex_decode_rgba32f(TEX_FMT_BPTC_SFLOAT, w.b, 4, 4, out);
    CHECK(out[0] < 0 && out[4] > 0 && out[4] == tex_half_to_float((uint16_t)((0x7FFF * 31) >> 5)), "BC6H signed: %g %g", out[0], out[4]);
    /* reserved mode (10011) -> zeros */
    memset(&w, 0, sizeof w); bw_put(&w, 0x13, 5);
    tex_decode_rgba32f(TEX_FMT_BPTC_UFLOAT, w.b, 4, 4, out);
    CHECK(out[0] == 0.0f, "BC6H reserved");
}

/* ASTC block: 1 partition, CEM 8 (RGB, 8-bit endpoints), 4x4 weight grid with 2-bit weights (mode 0x42) */
static void astc_make_cem8(BW *w, uint32_t mode, const int *e0, const int *e1, const uint32_t *weights, int nw, int wbits) {
    int wpos = 0, i;
    memset(w, 0, sizeof *w);
    bw_put(w, mode, 11);
    bw_put(w, 0, 2);                  /* 1 partition */
    bw_put(w, 8, 4);                  /* CEM 8 */
    bw_put(w, (uint32_t)e0[0], 8); bw_put(w, (uint32_t)e1[0], 8);
    bw_put(w, (uint32_t)e0[1], 8); bw_put(w, (uint32_t)e1[1], 8);
    bw_put(w, (uint32_t)e0[2], 8); bw_put(w, (uint32_t)e1[2], 8);
    for (i = 0; i < nw; i++) bw_weight(w, &wpos, weights[i], wbits);
}
static int astc_expect(int e0, int e1, int w, int srgb) {
    int c0 = srgb ? (e0 << 8) | 0x80 : (e0 << 8) | e0, c1 = srgb ? (e1 << 8) | 0x80 : (e1 << 8) | e1, v = (c0 * (64 - w) + c1 * w + 32) >> 6;
    return srgb ? v >> 8 : v == 65535 ? 255 : (v * 255 + 32768) >> 16;
}

static void test_astc(void) {
    BW w;
    uint8_t out[12 * 12 * 4];
    int i, x, y;
    static const int fmts[14] = {0x79, 0x7A, 0x7B, 0x7C, 0x7D, 0x7E, 0x7F, 0x80, 0x81, 0x82, 0x83, 0x84, 0x85, 0x86};
    unsigned bad0 = tex_astc_bad_blocks;
    /* void extent LDR in every footprint: colour (0x1234, 0x5678, 0x9ABC, 0xDEF0) -> (0x12, 0x56, 0x9A, 0xDE) */
    for (i = 0; i < 14; i++) {
        const TexFormat *f = tex_format(fmts[i]);
        memset(&w, 0, sizeof w);
        bw_put(&w, 0x1FC, 9); bw_put(&w, 0, 1); bw_put(&w, 3, 2);
        bw_put(&w, 0x1FFF, 13); bw_put(&w, 0x1FFF, 13); bw_put(&w, 0x1FFF, 13); bw_put(&w, 0x1FFF, 13);
        bw_put(&w, 0x1234, 16); bw_put(&w, 0x5678, 16); bw_put(&w, 0x9ABC, 16); bw_put(&w, 0xDEF0, 16);
        tex_decode_block_rgba8(fmts[i], w.b, out, f->bw * 4);
        for (y = 0; y < f->bh; y++) for (x = 0; x < f->bw; x++) {
            const uint8_t *p = out + (y * f->bw + x) * 4;
            if (!(p[0] == 0x12 && p[1] == 0x56 && p[2] == 0x9A && p[3] == 0xDE)) { CHECK(0, "ASTC %s void extent pixel (%d,%d) = %d,%d,%d,%d", f->name, x, y, p[0], p[1], p[2], p[3]); goto next; }
        }
        g_pass++;
    next:;
    }
    /* 4x4, 4x4 grid, 2-bit weights 0..3 (-> 0, 21, 43, 64), e0 = (0, 40, 200), e1 = (255, 60, 20): blue contraction NOT taken (sum e1 >= sum e0) */
    {
        int e0[3] = {0, 40, 200}, e1[3] = {255, 60, 20};
        uint32_t wt[16];
        for (i = 0; i < 16; i++) wt[i] = (uint32_t)(i & 3);
        astc_make_cem8(&w, 0x42, e0, e1, wt, 16, 2);
        tex_decode_block_rgba8(TEX_FMT_ASTC_4x4, w.b, out, 16);
        for (i = 0; i < 16; i++) {
            static const int wq[4] = {0, 21, 43, 64};
            int c, ok = 1;
            for (c = 0; c < 3; c++) if (out[i * 4 + c] != astc_expect(e0[c], e1[c], wq[i & 3], 0)) ok = 0;
            if (out[i * 4 + 3] != 255) ok = 0;
            CHECK(ok, "ASTC 4x4 CEM8 pixel %d = %d,%d,%d,%d expected %d,%d,%d", i, out[i * 4], out[i * 4 + 1], out[i * 4 + 2], out[i * 4 + 3], astc_expect(e0[0], e1[0], wq[i & 3], 0), astc_expect(e0[1], e1[1], wq[i & 3], 0), astc_expect(e0[2], e1[2], wq[i & 3], 0));
        }
        tex_decode_block_rgba8(TEX_FMT_ASTC_4x4_SRGB, w.b, out, 16);
        for (i = 0; i < 16; i++) {
            static const int wq[4] = {0, 21, 43, 64};
            int c, ok = 1;
            for (c = 0; c < 3; c++) if (out[i * 4 + c] != astc_expect(e0[c], e1[c], wq[i & 3], 1)) ok = 0;
            CHECK(ok, "ASTC 4x4 sRGB pixel %d = %d,%d,%d", i, out[i * 4], out[i * 4 + 1], out[i * 4 + 2]);
        }
        /* blue contraction taken: e0 brighter than e1 -> endpoints swapped and contracted */
        {
            int a0[3] = {200, 100, 50}, a1[3] = {10, 20, 30}, b0[3], b1[3];
            astc_make_cem8(&w, 0x42, a0, a1, wt, 16, 2);
            tex_decode_block_rgba8(TEX_FMT_ASTC_4x4, w.b, out, 16);
            b0[0] = (a1[0] + a1[2]) >> 1; b0[1] = (a1[1] + a1[2]) >> 1; b0[2] = a1[2];
            b1[0] = (a0[0] + a0[2]) >> 1; b1[1] = (a0[1] + a0[2]) >> 1; b1[2] = a0[2];
            CHECK(out[0] == astc_expect(b0[0], b1[0], 0, 0) && out[1] == astc_expect(b0[1], b1[1], 0, 0) && out[2] == b0[2] && out[3 * 4] == astc_expect(b0[0], b1[0], 64, 0), "ASTC blue contraction: %d %d %d / %d (expected %d %d %d / %d)", out[0], out[1], out[2], out[12], b0[0], b0[1], b0[2], b1[0]);
        }
    }
    /* bigger footprints with a 4x4 weight grid and uniform weights: infill must give exactly the weight */
    for (i = 1; i < 14; i++) {
        const TexFormat *f = tex_format(fmts[i]);
        int e0[3] = {10, 20, 30}, e1[3] = {250, 240, 230}, k;
        uint32_t wt[16];
        for (k = 0; k < 16; k++) wt[k] = 1;
        astc_make_cem8(&w, 0x42, e0, e1, wt, 16, 2);
        tex_decode_block_rgba8(fmts[i], w.b, out, f->bw * 4);
        for (y = 0; y < f->bh; y++) for (x = 0; x < f->bw; x++) {
            const uint8_t *p = out + (y * f->bw + x) * 4;
            if (p[0] != astc_expect(10, 250, 21, 0) || p[1] != astc_expect(20, 240, 21, 0) || p[2] != astc_expect(30, 230, 21, 0) || p[3] != 255) {
                CHECK(0, "ASTC %s uniform weights pixel (%d,%d) = %d,%d,%d,%d", f->name, x, y, p[0], p[1], p[2], p[3]); goto next2;
            }
        }
        g_pass++;
    next2:;
    }
    /* 6x6 block with a 6x6 grid of 1-bit weights (layout 9, R = 2: mode 0x104), checkerboard weights: texel (x,y) gets exactly weight (x+y)&1 */
    {
        const TexFormat *f = tex_format(TEX_FMT_ASTC_6x6);
        int e0[3] = {0, 0, 0}, e1[3] = {255, 255, 255};
        uint32_t wt[36];
        for (i = 0; i < 36; i++) wt[i] = (uint32_t)(((i % 6) + (i / 6)) & 1);
        astc_make_cem8(&w, 0x104, e0, e1, wt, 36, 1);
        tex_decode_block_rgba8(TEX_FMT_ASTC_6x6, w.b, out, f->bw * 4);
        for (y = 0; y < 6; y++) for (x = 0; x < 6; x++) {
            const uint8_t *p = out + (y * 6 + x) * 4;
            int e = ((x + y) & 1) ? 255 : 0;
            if (p[0] != e || p[1] != e || p[2] != e) { CHECK(0, "ASTC 6x6 full grid pixel (%d,%d) = %d expected %d", x, y, p[0], e); goto next3; }
        }
        g_pass++;
    next3:;
    }
    /* 2 partitions with identical endpoints (hash irrelevant): mode 0x53 (4x4 grid, 3-bit weights), CEM 8 + 8 at 4 bits each */
    {
        int wpos = 0, k;
        memset(&w, 0, sizeof w);
        bw_put(&w, 0x53, 11); bw_put(&w, 1, 2); bw_put(&w, 37, 10); bw_put(&w, 8 << 2, 6);
        for (k = 0; k < 2; k++) { bw_put(&w, 1, 4); bw_put(&w, 15, 4); bw_put(&w, 2, 4); bw_put(&w, 14, 4); bw_put(&w, 3, 4); bw_put(&w, 13, 4); }
        for (i = 0; i < 16; i++) bw_weight(&w, &wpos, (uint32_t)(i & 7), 3);
        tex_decode_block_rgba8(TEX_FMT_ASTC_4x4, w.b, out, 16);
        for (i = 0; i < 16; i++) {
            int wq = (i & 7) * 9 + ((i & 7) > 3 ? 1 : 0);     /* 3-bit: v<<3|v = 9v, 0..63 (+1 above 32) */
            int ok = out[i * 4] == astc_expect(0x11, 0xFF, wq, 0) && out[i * 4 + 1] == astc_expect(0x22, 0xEE, wq, 0) && out[i * 4 + 2] == astc_expect(0x33, 0xDD, wq, 0);
            CHECK(ok, "ASTC 2-partition pixel %d = %d,%d,%d expected %d,%d,%d", i, out[i * 4], out[i * 4 + 1], out[i * 4 + 2], astc_expect(0x11, 0xFF, wq, 0), astc_expect(0x22, 0xEE, wq, 0), astc_expect(0x33, 0xDD, wq, 0));
        }
    }
    /* dual plane: mode 0x441 (4x4 grid, 1-bit weights, D), CEM 8, CCS = 2 (blue uses plane 2); plane 1 weights all 0, plane 2 all 1 */
    {
        int wpos = 0, e0[3] = {0, 0, 0}, e1[3] = {255, 255, 255};
        memset(&w, 0, sizeof w);
        bw_put(&w, 0x441, 11); bw_put(&w, 0, 2); bw_put(&w, 8, 4);
        bw_put(&w, (uint32_t)e0[0], 8); bw_put(&w, (uint32_t)e1[0], 8); bw_put(&w, (uint32_t)e0[1], 8); bw_put(&w, (uint32_t)e1[1], 8); bw_put(&w, (uint32_t)e0[2], 8); bw_put(&w, (uint32_t)e1[2], 8);
        bw_set(&w, 128 - 32 - 2, 2, 2);          /* CCS just below the 32 weight bits */
        for (i = 0; i < 16; i++) { bw_weight(&w, &wpos, 0, 1); bw_weight(&w, &wpos, 1, 1); }
        tex_decode_block_rgba8(TEX_FMT_ASTC_4x4, w.b, out, 16);
        CHECK(out[0] == 0 && out[1] == 0 && out[2] == 255 && out[3] == 255 && out[15 * 4 + 2] == 255 && out[15 * 4] == 0, "ASTC dual plane: %d %d %d %d", out[0], out[1], out[2], out[3]);
    }
    /* CEM 12 (RGBA direct) with alpha */
    {
        int wpos = 0;
        memset(&w, 0, sizeof w);
        bw_put(&w, 0x42, 11); bw_put(&w, 0, 2); bw_put(&w, 12, 4);
        bw_put(&w, 10, 8); bw_put(&w, 20, 8); bw_put(&w, 30, 8); bw_put(&w, 40, 8); bw_put(&w, 50, 8); bw_put(&w, 60, 8); bw_put(&w, 70, 8); bw_put(&w, 80, 8);
        for (i = 0; i < 16; i++) bw_weight(&w, &wpos, 3, 2);
        tex_decode_block_rgba8(TEX_FMT_ASTC_4x4, w.b, out, 16);
        CHECK(out[0] == 20 && out[1] == 40 && out[2] == 60 && out[3] == 80, "ASTC CEM 12: %d %d %d %d", out[0], out[1], out[2], out[3]);
    }
    /* 3 and 4 partitions with distinct endpoints: every texel must take the colour of the partition the
     * specification's selection function gives (mode 0x42, 2-bit weights all 0 -> endpoint 0 of each partition;
     * CEM 0 luminance pairs for 4 partitions, CEM 8 at reduced precision for 3) */
    {
        int seed, parts, fi;
        for (fi = 0; fi < 14; fi += 3) for (parts = 3; parts <= 4; parts++) for (seed = 0; seed < 1024; seed += 37) {
            const TexFormat *f = tex_format(fmts[fi]);
            int ok = 1, small_blk = f->bw * f->bh < 31;
            memset(&w, 0, sizeof w);
            bw_put(&w, 0x42, 11); bw_put(&w, (uint32_t)(parts - 1), 2); bw_put(&w, (uint32_t)seed, 10); bw_put(&w, 0, 6);     /* all partitions CEM 0 (luminance direct) */
            for (i = 0; i < parts; i++) { bw_put(&w, (uint32_t)(i * 50 + 10), 8); bw_put(&w, 255, 8); }                    /* 67 colour bits: 6 or 8 values at 8 bits */
            tex_decode_block_rgba8(fmts[fi], w.b, out, f->bw * 4);
            for (y = 0; y < f->bh; y++) for (x = 0; x < f->bw; x++) {
                int pp = tex_astc_partition_reference(seed, x, y, parts, small_blk);
                const uint8_t *q = out + (y * f->bw + x) * 4;
                if (q[0] != pp * 50 + 10 || q[1] != q[0] || q[2] != q[0] || q[3] != 255) ok = 0;
            }
            CHECK(ok, "ASTC %s %d partitions seed %d: texels do not follow the partition function", f->name, parts, seed);
        }
    }
    /* invalid block mode -> error colour, counted */
    memset(&w, 0, sizeof w);
    tex_decode_block_rgba8(TEX_FMT_ASTC_4x4, w.b, out, 16);
    CHECK(out[0] == 255 && out[1] == 0 && out[2] == 255 && tex_astc_bad_blocks == bad0 + 1, "ASTC invalid block -> magenta (%d %d %d, bad %u)", out[0], out[1], out[2], tex_astc_bad_blocks - bad0);
    /* partial blocks at the edge of a 5x3 ASTC 4x4 image: second block column clipped */
    {
        uint8_t img[2 * 16], rgba[5 * 3 * 4];
        int e0[3] = {0, 0, 0}, e1[3] = {255, 255, 255};
        uint32_t wt[16];
        for (i = 0; i < 16; i++) wt[i] = 3;
        astc_make_cem8(&w, 0x42, e0, e1, wt, 16, 2);
        memcpy(img, w.b, 16);
        for (i = 0; i < 16; i++) wt[i] = 0;
        astc_make_cem8(&w, 0x42, e0, e1, wt, 16, 2);
        memcpy(img + 16, w.b, 16);
        memset(rgba, 7, sizeof rgba);
        tex_decode_rgba8(TEX_FMT_ASTC_4x4, img, 5, 3, rgba);
        CHECK(rgba[0] == 255 && rgba[(2 * 5 + 3) * 4] == 255 && rgba[(2 * 5 + 4) * 4] == 0 && rgba[4 * 4] == 0, "clipped decode: %d %d %d %d", rgba[0], rgba[(2 * 5 + 3) * 4], rgba[(2 * 5 + 4) * 4], rgba[4 * 4]);
    }
}

static void test_convert(void) {
    uint8_t out[16];
    uint16_t h = tex_float_to_half(0.5f);
    uint32_t v;
    CHECK(tex_half_to_float(h) == 0.5f && tex_half_to_float(0x3C00) == 1.0f && tex_half_to_float(0x7BFF) == 65504.0f && tex_half_to_float(0xC000) == -2.0f, "half conversions");
    CHECK(tex_float_to_half(65504.0f) == 0x7BFF && tex_float_to_half(-2.0f) == 0xC000 && tex_float_to_half(0.0f) == 0, "float to half");
    { uint8_t px[4] = {1, 2, 3, 4}; tex_convert_rgba8(TEX_FMT_BGRA8, px, 1, 1, out); CHECK(out[0] == 3 && out[1] == 2 && out[2] == 1 && out[3] == 4, "BGRA8 convert"); }
    { uint8_t px[4] = {1, 2, 3, 4}; tex_convert_rgba8(TEX_FMT_RGBX8, px, 1, 1, out); CHECK(out[0] == 1 && out[3] == 255, "RGBX8 convert"); }
    { uint16_t px[4] = {0x3C00, 0x3800, 0, 0x3C00}; tex_convert_rgba8(TEX_FMT_RGBA16F, px, 1, 1, out); CHECK(out[0] == 255 && out[1] == 128 && out[2] == 0 && out[3] == 255, "RGBA16F convert %d %d %d %d", out[0], out[1], out[2], out[3]); }
    { float px[2] = {0.25f, 1.5f}; tex_convert_rgba8(0x16, px, 1, 1, out); CHECK(out[0] == 64 && out[1] == 255 && out[2] == 0 && out[3] == 255, "RG32F convert %d %d", out[0], out[1]); }
    v = (1023u << 20) | (512u << 10) | 0 | (3u << 30); tex_convert_rgba8(TEX_FMT_RGB10A2, &v, 1, 1, out); CHECK(out[0] == 0 && out[1] == 128 && out[2] == 255 && out[3] == 255, "RGB10A2 %d %d %d %d", out[0], out[1], out[2], out[3]);
    v = 0xF800; tex_convert_rgba8(TEX_FMT_RGB565, &v, 1, 1, out); CHECK(out[0] == 255 && out[2] == 0, "RGB565: R in the top bits (%d %d %d)", out[0], out[1], out[2]);
    v = 0xF800; tex_convert_rgba8(TEX_FMT_BGR565, &v, 1, 1, out); CHECK(out[2] == 255 && out[0] == 0, "BGR565: B in the top bits (%d %d %d)", out[0], out[1], out[2]);
    { uint8_t px[2] = {0x80, 0x40}; tex_convert_rgba8(TEX_FMT_R8, px, 2, 1, out); CHECK(out[0] == 0x80 && out[1] == 0 && out[3] == 255 && out[4] == 0x40, "R8 convert"); }
    { int8_t px[1] = {-127}; tex_convert_rgba8(0x02, px, 1, 1, out); CHECK(out[0] == 0, "R8SN convert %d", out[0]); }
}

static void test_layout_misc(void) {
    TexLayout L;
    /* linear texture */
    tex_layout(&L, TEX_TARGET_2D, TEX_FMT_RGBA8, 100, 10, 1, 1, TEX_FLAG_LINEAR, 512, -1);
    CHECK(L.linear && L.size == 5120 && L.lvl_linear_size[0] == 4000, "linear layout %zu", L.size);
    /* 1280x720 RGBA8 render target: bh 16, 1 level */
    tex_layout(&L, TEX_TARGET_2D, TEX_FMT_RGBA8, 1280, 720, 1, 1, 0, 0, -1);
    CHECK(L.bh_log2 == 4 && L.size == 5120 * 768, "720p layout bh %d size %zu", L.bh_log2, L.size);
    /* packaged block height overrides the rule */
    tex_layout(&L, TEX_TARGET_2D, TEX_FMT_BPTC_UNORM, 128, 128, 1, 8, 0, 0, 1);
    CHECK(L.bh_log2 == 1 && L.lvl_bh_log2[1] == 1 && L.lvl_bh_log2[2] == 0, "packaged bh override: %d %d %d", L.bh_log2, L.lvl_bh_log2[1], L.lvl_bh_log2[2]);
    /* mip chain clipping and level dims */
    tex_layout(&L, TEX_TARGET_2D, TEX_FMT_RGBA_DXT1, 20, 6, 1, 99, 0, 0, -1);
    CHECK(L.levels == 5 && L.lvl_w[4] == 1 && L.lvl_wb[0] == 5 && L.lvl_hb[0] == 2 && L.lvl_hb[1] == 1, "mip clipping levels %d", L.levels);
    /* 2D array: layers from depth, 3D: depth stays */
    tex_layout(&L, TEX_TARGET_2D_ARRAY, TEX_FMT_RGBA8, 64, 64, 5, 1, 0, 0, -1);
    CHECK(L.layers == 5 && L.depth == 1 && L.size == 5 * L.layer_stride, "2D array layers %d", L.layers);
    tex_layout(&L, TEX_TARGET_3D, TEX_FMT_RGBA8, 32, 32, 32, 6, 0, 0, -1);
    CHECK(L.layers == 1 && L.depth == 32 && L.levels == 6 && L.lvl_d[1] == 16 && L.bh_log2 == 0 && L.bd_log2 == 4 && L.lvl_bd_log2[2] == 3 && L.lvl_bd_log2[5] == 0, "3D layout: depth %d bh %d bd %d lvl5 bd %d", L.depth, L.bh_log2, L.bd_log2, L.lvl_bd_log2[5]);
    tex_layout(&L, TEX_TARGET_3D, TEX_FMT_RGBA8, 16, 16, 16, 1, 0, 0, -1);
    CHECK(L.bh_log2 == 0 && L.bd_log2 == 4 && L.size == 16384 && L.alignment == 8192, "3D 16^3 layout: bh %d bd %d size %zu", L.bh_log2, L.bd_log2, L.size);
    tex_layout(&L, TEX_TARGET_CUBEMAP, TEX_FMT_RGBA8, 16, 16, 1, 1, 0, 0, -1);
    CHECK(L.layers == 6 && L.layer_stride == 64 * 16 * 1 && L.size == 6 * 1024, "cubemap layout stride %zu", L.layer_stride);
    /* level pointers and deswizzle of a whole mip chain round-trips through swizzle */
    {
        uint8_t *lin = (uint8_t *)malloc(1 << 18), *bl = (uint8_t *)malloc(1 << 18), *back = (uint8_t *)malloc(1 << 18);
        int l;
        tex_layout(&L, TEX_TARGET_2D, TEX_FMT_RGBA_DXT5, 100, 60, 1, 7, 0, 0, -1);
        rnd_fill(lin, 1 << 18);
        memset(bl, 0, 1 << 18);
        for (l = 0; l < L.levels; l++) tex_swizzle_level(&L, l, lin + L.lvl_offset[l], bl + L.lvl_offset[l]);
        for (l = 0; l < L.levels; l++) tex_deswizzle_level(&L, l, tex_level_ptr(&L, bl, l, 0), back + L.lvl_offset[l]);
        for (l = 0; l < L.levels; l++) CHECK(!memcmp(lin + L.lvl_offset[l], back + L.lvl_offset[l], L.lvl_linear_size[l]), "level %d round trip", l);
        free(lin); free(bl); free(back);
    }
}

static void test_png(void) {
    uint8_t img[8 * 8 * 4];
    int i;
    for (i = 0; i < 64; i++) { img[i * 4] = (uint8_t)(i * 4); img[i * 4 + 1] = (uint8_t)(255 - i * 4); img[i * 4 + 2] = 128; img[i * 4 + 3] = 255; }
    CHECK(tex_write_png("tex_test_png.tmp.png", img, 8, 8) == 0, "png write");
    remove("tex_test_png.tmp.png");
}

static int cmd_self(void) {
    test_formats();
    test_swizzle();
    test_block_height_rule();
    test_storage_sizes();
    test_layout_misc();
    test_bc1_5();
    test_bc7();
    test_bc6h();
    test_astc();
    test_convert();
    test_png();
    printf("self: %d checks passed, %d failed\n", g_pass, g_fail);
    return g_fail ? 1 : 0;
}

/* ---------------------------------------------------------------- scan.txt storage-size agreement */
static int cmd_scan(const char *path) {
    FILE *fp = fopen(path, "r");
    char line[2048];
    int n = 0, ok = 0, mip_ok = 0, mip_n = 0, unknown = 0;
    if (!fp) { printf("cannot open %s\n", path); return 1; }
    while (fgets(line, sizeof line, fp)) {
        unsigned fmt; int w, h, d, mips, layers; unsigned dsize;
        char *p = strstr(line, "fmt ");
        TexLayout L;
        if (!p || sscanf(p, "fmt 0x%x %dx%dx%d mips %d layers %d dsize %u", &fmt, &w, &h, &d, &mips, &layers, &dsize) != 7) continue;
        n++;
        if (nutexb_layout(&L, (int)fmt, w, h, d, mips, layers) < 0) { unknown++; continue; }
        if (L.data_size == dsize) ok++;
        else printf("mismatch: %s", line);
        p = strstr(line, "mips (");
        if (p) {
            int l = 0;
            p += 6;
            while (*p && *p != ')' && l < L.levels) {
                unsigned ms = (unsigned)strtoul(p, &p, 10);
                mip_n++;
                if (ms == L.lvl_linear_size[l]) mip_ok++;
                else if (mip_n - mip_ok < 10) printf("mip %d linear size %zu, footer %u: %s", l, L.lvl_linear_size[l], ms, line);
                l++;
                while (*p == ',' || *p == ' ') p++;
            }
        }
    }
    fclose(fp);
    printf("scan: %d textures, storage size agrees for %d (%d unknown formats); per-level linear sizes agree for %d of %d\n", n, ok, unknown, mip_ok, mip_n);
    return ok + unknown == n ? 0 : 1;
}

/* ---------------------------------------------------------------- decode helpers */
static int decode_level_to_png(const char *out, int nf, const uint8_t *packed, int w, int h, int d) {
    const TexFormat *f = tex_format(nf);
    uint8_t *rgba = (uint8_t *)malloc((size_t)w * h * d * 4);
    int z, r = 0;
    size_t lsize = (size_t)((w + f->bw - 1) / f->bw) * ((h + f->bh - 1) / f->bh) * f->bpb;
    for (z = 0; z < d; z++) {
        if (f->codec) r |= tex_decode_rgba8(nf, packed + z * lsize, w, h, rgba + (size_t)z * w * h * 4);
        else r |= tex_convert_rgba8(nf, packed + z * lsize, w, h, rgba + (size_t)z * w * h * 4);
    }
    if (r) { printf("no decoder for format 0x%x\n", nf); free(rgba); return 1; }
    r = tex_write_png(out, rgba, w, h * d);
    free(rgba);
    return r;
}

static int cmd_nutexb(const char *path, const char *out, int layer, int level) {
    size_t n;
    uint8_t *d = read_file(path, &n), *packed;
    Nutexb f;
    TexLayout L;
    int nf, l, r;
    if (!d) { printf("cannot read %s\n", path); return 1; }
    if (nutexb_parse(d, n, &f)) { printf("%s: no nutexb footer\n", path); return 1; }
    nf = nutexb_to_nvn(f.fmt);
    if (nf < 0) { printf("nutexb format 0x%02x not mapped\n", f.fmt); return 1; }
    nutexb_layout(&L, f.fmt, f.w, f.h, f.d, f.mips, f.layers);
    printf("%s: '%s' %dx%dx%d fmt 0x%02x (%s) mips %d layers %d data %u bytes; layout: bh %d size %zu (%s), layer stride %zu\n", path, f.name, f.w, f.h, f.d, f.fmt, tex_format(nf)->name, f.mips, f.layers, f.dsize,
           L.bh_log2, L.data_size, L.data_size == f.dsize ? "agrees" : "DIFFERS", L.layer_stride);
    for (l = 0; l < L.levels; l++) printf("  level %d: %dx%dx%d bh %d bd %d offset %zu swizzled %zu linear %zu (footer %u)\n", l, L.lvl_w[l], L.lvl_h[l], L.lvl_d[l], L.lvl_bh_log2[l], L.lvl_bd_log2[l], L.lvl_offset[l], L.lvl_size[l], L.lvl_linear_size[l], f.mip_sizes[l]);
    if (layer >= L.layers) layer = 0;
    if (level >= L.levels) level = 0;
    if (L.data_size > n) { printf("layout larger than the file\n"); return 1; }
    packed = (uint8_t *)malloc(L.lvl_linear_size[level]);
    tex_deswizzle_level(&L, level, tex_level_ptr(&L, d, level, layer), packed);
    r = decode_level_to_png(out, nf, packed, L.lvl_w[level], L.lvl_h[level], L.lvl_d[level]);
    if (!r) printf("wrote %s (%dx%d, layer %d level %d)%s\n", out, L.lvl_w[level], L.lvl_h[level] * L.lvl_d[level], layer, level, tex_astc_hdr_blocks || tex_astc_bad_blocks ? " (ASTC hdr/bad blocks)" : "");
    free(packed); free(d);
    return r;
}

static int cmd_decode(const char *raw, int w, int h, int nf, int bh, const char *out) {
    size_t n;
    uint8_t *d = read_file(raw, &n), *packed;
    TexLayout L;
    int r;
    if (!d) { printf("cannot read %s\n", raw); return 1; }
    if (!tex_format(nf)) { printf("unknown format 0x%x\n", nf); return 1; }
    tex_layout(&L, TEX_TARGET_2D, nf, w, h, 1, 1, 0, 0, bh);
    if (L.lvl_size[0] > n) { printf("level 0 needs %zu bytes, file has %zu\n", L.lvl_size[0], n); return 1; }
    packed = (uint8_t *)malloc(L.lvl_linear_size[0]);
    tex_deswizzle_level(&L, 0, d, packed);
    r = decode_level_to_png(out, nf, packed, w, h, 1);
    if (!r) printf("wrote %s (%dx%d %s, block height %d)\n", out, w, h, tex_format(nf)->name, L.bh_log2);
    free(packed); free(d);
    return r;
}

/* ---------------------------------------------------------------- BC7 three-subset partition 56 experiment
 * The NVIDIA driver uses texel 6 as the second anchor of this one partition where the published table
 * says 5 (found by `gl`: bit-exact with 6, 2 texels wrong per such block with 5). This mode looks for
 * such blocks in game data (nutexb files or a file of raw 16-byte blocks), decodes each both ways and
 * measures how well texels 5 and 6 fit their neighbours. Result on SSBU: the game has no such block. */
extern int tex_bc7_p56_anchor;
int tex_astc_partition_reference(int seed, int x, int y, int count, int small_block);   /* tex_decode.c */
static int cmd_bc7p56(int argc, char **argv) {
    int a, n56 = 0, smoother5 = 0, smoother6 = 0, same = 0;
    long long rough5 = 0, rough6 = 0;
    for (a = 2; a < argc; a++) {
        size_t n;
        uint8_t *d = read_file(argv[a], &n), *packed;
        Nutexb f;
        TexLayout L;
        size_t i, nb;
        if (!d) continue;
        if (nutexb_parse(d, n, &f)) {                       /* a file of raw 16-byte blocks */
            packed = (uint8_t *)malloc(n + 1); memcpy(packed, d, n); nb = n / 16;
        } else {
            if (f.fmt != 0xE0 && f.fmt != 0xE5) { free(d); continue; }
            nutexb_layout(&L, f.fmt, f.w, f.h, f.d, f.mips, f.layers);
            packed = (uint8_t *)malloc(L.lvl_linear_size[0]);
            tex_deswizzle_level(&L, 0, d, packed);
            nb = L.lvl_linear_size[0] / 16;
        }
        for (i = 0; i < nb; i++) {
            const uint8_t *b = packed + i * 16;
            uint8_t o5[64], o6[64];
            int r5 = 0, r6 = 0, c;
            static const int pairs[6][2] = {{5, 4}, {6, 7}, {5, 1}, {6, 2}, {5, 9}, {6, 10}};
            if ((b[0] & 7) != 4 || (((b[0] >> 3) | (b[1] << 5)) & 63) != 56) continue;
            n56++;
            tex_bc7_p56_anchor = 5; tex_decode_block_rgba8(TEX_FMT_BPTC_UNORM, b, o5, 16);
            tex_bc7_p56_anchor = 6; tex_decode_block_rgba8(TEX_FMT_BPTC_UNORM, b, o6, 16);
            tex_bc7_p56_anchor = 6;
            for (c = 0; c < 6; c++) { int k; for (k = 0; k < 3; k++) { r5 += abs(o5[pairs[c][0] * 4 + k] - o5[pairs[c][1] * 4 + k]); r6 += abs(o6[pairs[c][0] * 4 + k] - o6[pairs[c][1] * 4 + k]); } }
            rough5 += r5; rough6 += r6;
            if (r5 < r6) smoother5++; else if (r6 < r5) smoother6++; else same++;
        }
        free(packed); free(d);
    }
    printf("bc7p56: %d mode-2 partition-56 blocks; anchor 5 smoother in %d, anchor 6 smoother in %d, equal %d; total roughness anchor 5: %lld, anchor 6: %lld\n", n56, smoother5, smoother6, same, rough5, rough6);
    return 0;
}

/* ---------------------------------------------------------------- GL cross-check */
typedef void(APIENTRY *PFN_CTI2D)(GLenum, GLint, GLenum, GLsizei, GLsizei, GLint, GLsizei, const void *);
static PFN_CTI2D p_glCompressedTexImage2D;

static int gl_init(void) {
    WNDCLASSA wc;
    HWND hwnd;
    HDC dc;
    HGLRC rc;
    PIXELFORMATDESCRIPTOR pfd;
    memset(&wc, 0, sizeof wc);
    wc.lpfnWndProc = DefWindowProcA; wc.hInstance = GetModuleHandleA(NULL); wc.lpszClassName = "tex_test_gl";
    RegisterClassA(&wc);
    hwnd = CreateWindowExA(0, "tex_test_gl", "tex_test", WS_OVERLAPPEDWINDOW, 0, 0, 64, 64, NULL, NULL, wc.hInstance, NULL);
    dc = GetDC(hwnd);
    memset(&pfd, 0, sizeof pfd);
    pfd.nSize = sizeof pfd; pfd.nVersion = 1; pfd.dwFlags = PFD_DRAW_TO_WINDOW | PFD_SUPPORT_OPENGL; pfd.iPixelType = PFD_TYPE_RGBA; pfd.cColorBits = 32;
    SetPixelFormat(dc, ChoosePixelFormat(dc, &pfd), &pfd);
    rc = wglCreateContext(dc);
    if (!rc || !wglMakeCurrent(dc, rc)) return -1;
    p_glCompressedTexImage2D = (PFN_CTI2D)wglGetProcAddress("glCompressedTexImage2D");
    printf("GL: %s / %s %s\n", glGetString(GL_VENDOR), glGetString(GL_RENDERER), glGetString(GL_VERSION));
    return p_glCompressedTexImage2D ? 0 : -1;
}

/* synthetic ASTC blocks that are always valid (single partition CEM 8/12, 4x4 grid, or 2-partition CEM 8+8) */
static void astc_random_valid(uint8_t *blk, int bw, int bh) {
    BW w;
    int kind = (int)(rnd() % 3), i, wpos = 0;
    (void)bw; (void)bh;
    memset(&w, 0, sizeof w);
    if (kind == 0) {
        bw_put(&w, 0x42, 11); bw_put(&w, 0, 2); bw_put(&w, 8, 4);
        for (i = 0; i < 6; i++) bw_put(&w, rnd() & 255, 8);
        for (i = 0; i < 16; i++) bw_weight(&w, &wpos, rnd() & 3, 2);
    } else if (kind == 1) {
        bw_put(&w, 0x42, 11); bw_put(&w, 0, 2); bw_put(&w, 12, 4);
        for (i = 0; i < 8; i++) bw_put(&w, rnd() & 255, 8);
        for (i = 0; i < 16; i++) bw_weight(&w, &wpos, rnd() & 3, 2);
    } else {
        bw_put(&w, 0x53, 11); bw_put(&w, 1, 2); bw_put(&w, rnd() & 1023, 10); bw_put(&w, 8 << 2, 6);
        for (i = 0; i < 12; i++) bw_put(&w, rnd() & 15, 4);
        for (i = 0; i < 16; i++) bw_weight(&w, &wpos, rnd() & 7, 3);
    }
    memcpy(blk, w.b, 16);
}

/* ASTC against an external reference decoder (the GL driver has no ASTC):
 *   astcgen <format> <n> <blocks.bin>           n random + n synthetic valid blocks
 *   astccmp <format> <blocks.bin> <ref.rgba>    ref.rgba = bw*bh RGBA8 texels per block, block after block
 * The reference used was the decoder of the suyu emulator built as a stand-alone tool (not part of this
 * project); it reports errors as 0,0,0,0 and decodes HDR blocks, which this library rejects (magenta). */
static int cmd_astcgen(int nf, int n, const char *path) {
    const TexFormat *f = tex_format(nf);
    FILE *fp;
    uint8_t blk[16];
    int i;
    if (!f || f->codec != TEX_CODEC_ASTC) return 2;
    fp = fopen(path, "wb");
    if (!fp) return 1;
    g_rng ^= (uint64_t)nf * 0x100000001B3ULL;
    for (i = 0; i < n; i++) { rnd_fill(blk, 16); fwrite(blk, 1, 16, fp); }
    for (i = 0; i < n; i++) { astc_random_valid(blk, f->bw, f->bh); fwrite(blk, 1, 16, fp); }
    fclose(fp);
    return 0;
}

extern int tex_astc_test_full_bise;
static int cmd_astccmp(int nf, const char *blocks, const char *ref) {
    const TexFormat *f = tex_format(nf);
    size_t nb, nr, i;
    uint8_t *b = read_file(blocks, &nb), *r = read_file(ref, &nr), mine[12 * 12 * 4];
    int px, exact = 0, within1 = 0, differ = 0, both_bad = 0, mine_rejects = 0, ref_rejects = 0, hdr = 0, shown = 0, maxd_all = 0;
    tex_astc_test_full_bise = getenv("TEX_ASTC_FULL_BISE") != NULL;
    if (!f || !b || !r) { printf("astccmp: cannot read inputs\n"); return 2; }
    px = f->bw * f->bh;
    nb /= 16;
    if (nr < nb * (size_t)px * 4) { printf("astccmp: reference too short\n"); return 2; }
    for (i = 0; i < nb; i++) {
        unsigned bad0 = tex_astc_bad_blocks, hdr0 = tex_astc_hdr_blocks;
        const uint8_t *rr = r + i * (size_t)px * 4;
        int k, maxd = 0, ref_zero = 1;
        tex_decode_block_rgba8(nf, b + i * 16, mine, f->bw * 4);
        for (k = 0; k < px * 4; k++) if (rr[k]) ref_zero = 0;
        if (tex_astc_hdr_blocks != hdr0) { hdr++; continue; }
        if (tex_astc_bad_blocks != bad0) { if (ref_zero) both_bad++; else mine_rejects++; continue; }
        if (ref_zero) { int z = 1; for (k = 0; k < px * 4; k++) if (mine[k]) z = 0; if (!z) { ref_rejects++; continue; } }
        for (k = 0; k < px * 4; k++) { int d = abs((int)mine[k] - (int)rr[k]); if (d > maxd) maxd = d; }
        if (maxd > maxd_all) maxd_all = maxd;
        if (maxd == 0) exact++; else if (maxd <= 1) within1++;
        else {
            differ++;
            if (shown++ < 4) {
                printf("  differs (max %d): block ", maxd);
                for (k = 0; k < 16; k++) printf("%02x", b[i * 16 + k]);
                printf(" mode 0x%03x parts %d\n   mine:", (b[i * 16] | b[i * 16 + 1] << 8) & 0x7FF, ((b[i * 16 + 1] >> 3) & 3) + 1);
                for (k = 0; k < 16 && k < px * 4; k++) printf(" %d", mine[k]);
                printf("\n   ref: ");
                for (k = 0; k < 16 && k < px * 4; k++) printf(" %d", rr[k]);
                printf("\n");
            }
        }
    }
    printf("  %-12s %zu blocks: %d identical, %d within 1, %d DIFFER (max %d); both reject %d; HDR (not decoded here) %d; only this library rejects %d; only the reference rejects %d\n",
           f->name, nb, exact, within1, differ, maxd_all, both_bad, hdr, mine_rejects, ref_rejects);
    free(b); free(r);
    return differ ? 1 : 0;
}

static int gl_check_format(int nf, int iters, int synthetic) {
    const TexFormat *f = tex_format(nf);
    int w = f->bw * 8, h = f->bh * 8, nblk = 64, it, i, maxd = 0, nbad = 0, ntot = 0, hw_fail = 0;
    uint8_t *data = (uint8_t *)malloc((size_t)nblk * f->bpb), *mine = (uint8_t *)malloc((size_t)w * h * 4), *hw = (uint8_t *)malloc((size_t)w * h * 4);
    float *minef = (float *)malloc((size_t)w * h * 16), *hwf = (float *)malloc((size_t)w * h * 16);
    int is_float = f->is_float || f->snorm, tol = f->codec == TEX_CODEC_BC7 ? 0 : f->codec == TEX_CODEC_ASTC ? 1 : 2;
    GLuint tex;
    glGenTextures(1, &tex);
    glBindTexture(GL_TEXTURE_2D, tex);
    while (glGetError()) {}
    for (it = 0; it < iters; it++) {
        unsigned bad0 = tex_astc_bad_blocks + tex_astc_hdr_blocks;
        if (synthetic && f->codec == TEX_CODEC_ASTC) for (i = 0; i < nblk; i++) astc_random_valid(data + i * 16, f->bw, f->bh);
        else rnd_fill(data, (size_t)nblk * f->bpb);
        p_glCompressedTexImage2D(GL_TEXTURE_2D, 0, f->gl_internal, w, h, 0, nblk * f->bpb, data);
        if (glGetError()) { hw_fail = 1; break; }
        if (is_float) {
            if (f->codec == TEX_CODEC_BC6H) glGetTexImage(GL_TEXTURE_2D, 0, GL_RGBA, GL_FLOAT, hwf);
            else {          /* snorm: read signed bytes (the driver's float readback of snorm textures is biased) */
                glGetTexImage(GL_TEXTURE_2D, 0, GL_RGBA, GL_BYTE, hw);
                for (i = 0; i < w * h * 4; i++) hwf[i] = (i & 3) == 3 ? 1.0f : (int8_t)hw[i] / 127.0f;
            }
            tex_decode_rgba32f(nf, data, w, h, minef);
            for (i = 0; i < w * h * 4; i++) {
                float a = minef[i], b = hwf[i], d = (float)fabs(a - b), rel = d / ((float)fabs(b) + 1e-6f);
                ntot++;
                if (f->codec == TEX_CODEC_BC6H ? (d > 1e-6f && rel > 1e-3f && (i & 3) != 3) : d > 0.0119f)     /* snorm bytes: 1.5 / 127 */ { if (nbad < 5) printf("  %s: value %d (pixel %d.%d) mine %g hw %g\n", f->name, i, i / 4, i & 3, a, b); nbad++; }
            }
        } else {
            glGetTexImage(GL_TEXTURE_2D, 0, GL_RGBA, GL_UNSIGNED_BYTE, hw);
            tex_decode_rgba8(nf, data, w, h, mine);
            for (i = 0; i < w * h * 4; i++) {
                int d = abs((int)mine[i] - (int)hw[i]);
                if ((i & 3) == 3 && f->ncomp == 3) continue;      /* RGB_DXT1: the NVIDIA readback reports alpha 0 for 3-colour index 3; sampling gives 1 */
                ntot++;
                if (d > maxd) maxd = d;
                if (d > tol && f->codec == TEX_CODEC_BC7 && getenv("TEX_DUMP")) { int bi = (i / 4 / w / f->bh) * (w / f->bw) + (i / 4 % w) / f->bw, k; printf("BLK px %d ch %d mine %d hw %d: ", ((i / 4 / w) & 3) * 4 + ((i / 4 % w) & 3), i & 3, mine[i], hw[i]); for (k = 0; k < 16; k++) printf("%02x", data[bi * 16 + k]); printf("\n"); }
                if (d > tol) { if (nbad < 5) printf("  %s: byte %d (pixel %d.%d, block %d) mine %d hw %d (block %02x%02x%02x%02x...)\n", f->name, i, i / 4, i & 3, (i / 4 / w / f->bh) * (w / f->bw) + (i / 4 % w) / f->bw, mine[i], hw[i], data[0], data[1], data[2], data[3]); nbad++; }
            }
        }
        if (f->codec == TEX_CODEC_ASTC && tex_astc_bad_blocks + tex_astc_hdr_blocks != bad0 && !synthetic) {}
    }
    glDeleteTextures(1, &tex);
    free(data); free(mine); free(hw); free(minef); free(hwf);
    if (hw_fail) { printf("  %-18s not supported by this GL driver (skipped)\n", f->name); return 0; }
    printf("  %-18s %s: %d values compared, %d differ beyond tolerance %d, max byte difference %d%s\n", f->name, nbad ? "FAIL" : "ok", ntot, nbad, tol, maxd, synthetic ? " (synthetic valid blocks)" : " (random blocks)");
    return nbad ? 1 : 0;
}

static int cmd_gl(void) {
    static const int fmts[] = {0x41, 0x42, 0x43, 0x44, 0x46, 0x49, 0x4A, 0x4B, 0x4C, 0x4D, 0x4E, 0x4F, 0x50};
    static const int astc[] = {0x79, 0x7A, 0x7B, 0x7C, 0x7D, 0x7E, 0x7F, 0x80, 0x81, 0x82, 0x83, 0x84, 0x85, 0x86, 0x87, 0x8B, 0x8E, 0x94};
    size_t i;
    int fails = 0;
    if (gl_init()) { printf("no GL context\n"); return 2; }
    for (i = 0; i < sizeof fmts / sizeof fmts[0]; i++) fails += gl_check_format(fmts[i], getenv("TEX_GL_ITERS") ? atoi(getenv("TEX_GL_ITERS")) : 40, 0);
    for (i = 0; i < sizeof astc / sizeof astc[0]; i++) { fails += gl_check_format(astc[i], 20, 0); fails += gl_check_format(astc[i], 20, 1); }
    printf("gl: %d formats failed\n", fails);
    return fails ? 1 : 0;
}

/* ---------------------------------------------------------------- benchmark */
static void bench_one(const char *name, int nf, const uint8_t *data, int w, int h, int reps) {
    const TexFormat *f = tex_format(nf);
    uint8_t *out = (uint8_t *)malloc((size_t)w * h * 4);
    float *outf = (float *)malloc((size_t)w * h * 16);
    double t0 = now_s(), dt;
    int r;
    size_t in_bytes = (size_t)((w + f->bw - 1) / f->bw) * ((h + f->bh - 1) / f->bh) * f->bpb;
    for (r = 0; r < reps; r++) { if (f->codec == TEX_CODEC_BC6H) tex_decode_rgba32f(nf, data, w, h, outf); else tex_decode_rgba8(nf, data, w, h, out); }
    dt = now_s() - t0;
    printf("  %-22s %dx%d: %.1f ms per image, %.0f MB/s compressed in, %.0f Mpixel/s\n", name, w, h, dt / reps * 1000, (double)in_bytes * reps / dt / 1048576.0, (double)w * h * reps / dt / 1e6);
    free(out); free(outf);
}

static int cmd_bench(void) {
    int w = 1024, h = 1024, i;
    uint8_t *data = (uint8_t *)malloc((size_t)w * h);   /* 1 byte per texel is enough for 16 B / 16 texels; ASTC 4x4 needs w*h bytes */
    size_t n;
    uint8_t *file;
    printf("bench (%dx%d images):\n", w, h);
    rnd_fill(data, (size_t)w * h);
    bench_one("BC1 random", 0x42, data, w, h, 20);
    bench_one("BC3 random", 0x44, data, w, h, 20);
    bench_one("BC4 random", 0x49, data, w, h, 20);
    bench_one("BC5 random", 0x4B, data, w, h, 20);
    bench_one("BC6H random", 0x50, data, w, h, 10);
    bench_one("BC7 random", 0x4D, data, w, h, 10);
    file = read_file("tex_samples\\fighter__mario__model__body__c00__def_mario_001_col.nutexb", &n);
    if (file) {
        TexLayout L;
        uint8_t *packed;
        tex_layout(&L, TEX_TARGET_2D, TEX_FMT_BPTC_UNORM_SRGB, 1024, 512, 1, 1, 0, 0, -1);
        packed = (uint8_t *)malloc(L.lvl_linear_size[0]);
        { double t0 = now_s(); for (i = 0; i < 50; i++) tex_deswizzle_level(&L, 0, file, packed); printf("  %-22s 1024x512: %.2f ms, %.0f MB/s\n", "deswizzle BC7 level", (now_s() - t0) / 50 * 1000, (double)L.lvl_size[0] * 50 / (now_s() - t0) / 1048576.0); }
        bench_one("BC7 game texture", 0x4E, packed, 1024, 512, 20);
        free(packed); free(file);
    }
    for (i = 0; i < w * h / 16; i++) astc_random_valid(data + i * 16, 4, 4);
    bench_one("ASTC 4x4 synthetic", 0x79, data, w, h, 5);
    bench_one("ASTC 6x6 synthetic", 0x7D, data, w, h, 5);
    bench_one("ASTC 8x8 synthetic", 0x80, data, w, h, 5);
    bench_one("ASTC 12x12 synthetic", 0x86, data, w, h, 5);
    rnd_fill(data, (size_t)w * h);
    bench_one("ASTC 4x4 random", 0x79, data, w, h, 5);
    free(data);
    return 0;
}

int main(int argc, char **argv) {
    if (argc < 2) { printf("usage: tex_test self | scan <scan.txt> | nutexb <file> <out.png> [layer] [level] | decode <raw> <w> <h> <format> <bhlog2> <out.png> | gl | bench\n"); return 2; }
    if (!strcmp(argv[1], "self")) return cmd_self();
    if (!strcmp(argv[1], "scan") && argc >= 3) return cmd_scan(argv[2]);
    if (!strcmp(argv[1], "nutexb") && argc >= 4) return cmd_nutexb(argv[2], argv[3], argc > 4 ? atoi(argv[4]) : 0, argc > 5 ? atoi(argv[5]) : 0);
    if (!strcmp(argv[1], "decode") && argc >= 8) return cmd_decode(argv[2], atoi(argv[3]), atoi(argv[4]), (int)strtol(argv[5], NULL, 0), atoi(argv[6]), argv[7]);
    if (!strcmp(argv[1], "astcblk") && argc >= 4) {       /* decode one block given as 32 hex digits, print the texels */
        uint8_t blk[16], out[12 * 12 * 4];
        const TexFormat *f = tex_format((int)strtol(argv[2], NULL, 0));
        int i, x, y;
        for (i = 0; i < 16; i++) { unsigned v = 0; sscanf(argv[3] + i * 2, "%2x", &v); blk[i] = (uint8_t)v; }
        tex_decode_block_rgba8(f->nvn, blk, out, f->bw * 4);
        for (y = 0; y < f->bh; y++) { for (x = 0; x < f->bw; x++) printf(" %3d,%3d,%3d,%3d", out[(y * f->bw + x) * 4], out[(y * f->bw + x) * 4 + 1], out[(y * f->bw + x) * 4 + 2], out[(y * f->bw + x) * 4 + 3]); printf("\n"); }
        return 0;
    }
    if (!strcmp(argv[1], "bc7p56")) return cmd_bc7p56(argc, argv);
    if (!strcmp(argv[1], "astcgen") && argc >= 5) return cmd_astcgen((int)strtol(argv[2], NULL, 0), atoi(argv[3]), argv[4]);
    if (!strcmp(argv[1], "astccmp") && argc >= 5) return cmd_astccmp((int)strtol(argv[2], NULL, 0), argv[3], argv[4]);
    if (!strcmp(argv[1], "gl")) { if (getenv("TEX_BC7_P56")) tex_bc7_p56_anchor = atoi(getenv("TEX_BC7_P56")); return cmd_gl(); }
    if (!strcmp(argv[1], "bench")) return cmd_bench();
    printf("bad arguments\n");
    return 2;
}
