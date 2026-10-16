// loose_files.c - LOOSE-FILE LAYER (plan\phases\N4_own_fighter.md section 3, N6_own_files.md, N7_own_files2.md). Part of OUR runtime.
// Serves files from a folder in place of the copies in the game's archive:
//     <root>\<name>\<archive path>        e.g.  characters\n3test\fighter\n3test\param\vl.prc
// <root> = SSBU_CHARACTERS, default "<exe folder>\..\characters". Every folder directly under <root> is one
// fighter / mod; below it the tree mirrors the archive's paths. No folder = nothing installed.
//
// This file contains no game content. It is written to be included: the includer defines Ctx, HookFn, HookOrig
// (fighter_sdk\include\hook.h for a mod DLL; the host's own declarations for the exe) and calls
//     loose_files_start(install, log)
// with the hook table's install function.
//
// STAGE 1 (N4): a path the ARCHIVE KNOWS. Hook point: the per-file decompress 0x71039a4040
// (zstd stream step: x0 context, x1 out {pointer, size, position}, x2 in {...}; returns 0 when the file is complete),
// called from the resource service's inflate thread 0x71035444c0. A replacement in our hook table sees the whole
// guest register context of the caller, and x19 (the resource service) and x27 (the loop index) are callee-saved
// registers of the inflate thread that are still intact at the entry of the callee. So: file info index =
// [service + 0x230] + x27, at the moment the callee returns 0. Then the loose file's bytes replace the content of
// the game's own buffer (loaded data[file info indice index]). So that the buffer is large enough, the decompressed
// size in the archive's in-memory table is raised to the loose file's size when the tables are first seen.
//
// STAGE 2 (N6, N7): paths the archive does NOT know, for a folder that has a manifest (fighter.json: "name", "donor")
// and at least one file. The archive's in-memory tables are GROWN once, when they are first seen: larger copies are
// allocated, the new rows appended, the pointers and counts in the game's objects switched (the old arrays are never
// freed: a reader that still holds an old pointer reads valid old rows).
//
// N7: THE LOAD GROUP. A fighter's files are read by the game as a DIRECTORY row ("fighter/<name>/c00"): the row names
// a range of file infos and a directory-offset row (one compressed stretch of the archive); the game's directory
// set-up 0x7103540860 counts a user for every file of the range (by the file info's PATH index) and the load thread
// 0x71035456d0 / inflate thread 0x71035444c0 walk the range (dir row + 0x20 start, + 0x24 count) and decompress each
// file into the buffer of ITS loaded-data row. So for every fighter folder a new directory row is made:
//     a copy of the donor's row with the new path hash and parent, the SAME directory-offset row and child list,
//     and a NEW range of file infos in the donor's order, where
//       - a file info that is the donor directory's own copy of a file ("own": the file's indice row names it) is a
//         NEW FILE: new file path row (new hash), new indice row, new loaded rows; it shares the donor file's
//         info-to-data and file-data rows, so the game decompresses the donor's bytes into the NEW file's buffer;
//       - any other file info of the range (files shared with other directories) is copied as it is.
//     The new hash of an own file: clone_files.json of the folder (tests\n5_clone_files.py) when the folder brings
//     the file - then stage 1's hook replaces the buffer's content with the folder's file ("served"); else the donor
//     path with its prefix "fighter/<donor>" or "effect/fighter/<donor>" renamed, computed without the name (crc32 is
//     linear: crc(P' + C) = crc(P + C) ^ shift(crc(P) ^ crc(P'), length of C)) - such a file keeps the donor's bytes
//     under its own name and own buffer (the donor fallback, counted in the log); else a private hash nobody asks for.
// Every new file and every new folder also gets entries in the SEARCH tables (the first of the game's two lookups).
// A loose file of a fighter folder that is in no group range gets a file row without a group (as in N6).
//
// Tables (13.0.4; names as in reference\smash-arc and reference\ARCropolis, offsets checked against the lifted code of
// 0x710353e330, 0x710353e4e0, 0x710353e5d0, 0x7103540450, 0x7103540860, 0x71035456d0 and 0x71035444c0):
//   resource service  *(0x7105331f28): +0xd0 filesystem info, +0x228 batch index, +0x22c batch count, +0x230 batch start
//   filesystem info   *(0x7105331f20): +0x08 loaded file paths (8 bytes: data index, loaded), +0x10 loaded datas
//                     (0x18 bytes: +0 buffer, +8 users, +0xc in use, +0xd state), +0x18 / +0x1c their lengths,
//                     +0x40 loaded directories (0x48 bytes, +8 bit 0 = in use; indexed by directory index, and by
//                     directory-offset index for the shared stretches), +0x48 their length,
//                     +0x78 -> { archive tables, search tables }
//   archive tables    +0x40 header (+4 file paths, +8 file info indices, +0xc directories, +0x18 / +0x28 / +0x44 file
//                     infos), +0x50 buckets ({total, bucket count} then {start, count} per bucket), +0x58 hash -> index,
//                     +0x60 file paths (0x20 bytes: path, extension, parent, file name; each hash40 | index << 40),
//                     +0x68 file info indices (8 bytes: +4 file info index), +0x70 directory hash -> index (sorted),
//                     +0x78 directories (0x34 bytes: +0 path | directory-offset index << 40, +8 name, +0x10 parent,
//                     +0x20 file info start, +0x24 count, +0x28 child start, +0x2c child count, +0x30 flags),
//                     +0x80 directory offsets (0x1c bytes), +0x88 child hashes, +0x90 file infos (16 bytes: path
//                     index, indice index, info-to-data index, flags), +0x98 info to data (12 bytes: +4 file data
//                     index), +0xa0 file datas (16 bytes: +4 compressed size, +8 decompressed size)
//   search tables     +0x08 counts {folders, path list indices, paths}, +0x10 folder index (sorted), +0x18 folder list
//                     (0x20 bytes: path, parent | child count << 40, file name, first child), +0x20 path index (sorted:
//                     hash40 | position in the indices << 40), +0x28 path list indices, +0x30 path list (0x20 bytes:
//                     path | next sibling << 40, parent, file name, extension)
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
#include <windows.h>

#define LF_MAX 4096
#define LF_MAX_FOLDERS 1024
#define LF_MAX_OWNERS 16
#define LF_MAX_NEW 16384
#define LF_MAX_GROUPS 64
#define LF_NPRE 2
#define LF_MASK40 0xffffffffffull
#define LF_NONE 0xffffffu
typedef struct {
    uint64_t hash;                  // hash40 of the archive path
    char *arc_path, *disk_path;
    uint32_t size;
    int32_t path_index;             // file path index in the archive, -1 = the archive has no such path
    uint32_t indice_index, info_index, data_index, arc_size;
    long served;
    int owner;                      // index of the fighter folder with a manifest, -1 = a plain file mod
    int is_new;                     // stage 2: the row was added by us
    uint64_t donor_hash;            // stage 2: the archive file whose data rows the new row shares
    uint64_t name_hash;             // B3: hash40 of the file NAME when the folder file is named "0x<name hash>.<ext>", else 0
} LooseFile;
typedef struct { char name[32], donor[32]; int files, new_files, renamed, private_rows, shared_rows; long served, donor_bytes_files; unsigned long long bytes; } LooseOwner;
typedef struct { uint64_t hash, parent_hash, name_hash, donor_hash; int owner, exists; uint32_t fpos, ipos; } LooseFolder;
// a file with a new identity: kind 1 = the folder brings it (loose file), 2 = renamed, the donor's bytes, 3 = private hash
typedef struct { uint64_t hash, parent_hash; int64_t donor_pi; uint32_t donor_xi, donor_ii, info_pos; int loose, owner, kind; } LooseNew;
typedef struct { uint64_t hash, donor_hash, parent_hash; int owner, is_link; uint32_t dir_index, donor_dir, info_start, count, child_start, child_count, fo_new, fo_src, fo_target;
                 long finished; char path[96]; } LooseGroup;
static LooseFile g_lf[LF_MAX];
static LooseOwner g_lf_owner[LF_MAX_OWNERS];
static LooseFolder g_lf_folder[LF_MAX_FOLDERS];
static LooseNew g_lf_new[LF_MAX_NEW];
static LooseGroup g_lf_group[LF_MAX_GROUPS];
static uint64_t g_lf_child[LF_MAX_GROUPS * 8]; static int g_lf_child_count, g_lf_fo_count;
static struct { uint32_t donor_ii; int32_t new_index; } g_lf_plan[LF_MAX_NEW * 2];     // the new file infos, in order
static int g_lf_count, g_lf_resolved, g_lf_owner_count, g_lf_folder_count, g_lf_new_count, g_lf_grown, g_lf_group_count, g_lf_plan_count;
static long g_lf_served_new, g_lf_done_kind[8]; static unsigned long long g_lf_served_new_bytes;
static volatile int g_lf_scanned;
static uint32_t g_lf_first_new_info;
static int g_lf_search_on, g_lf_early;
#define LF_MAX_TMPL 1024
static struct { uint32_t itd, data_index, size, info; } g_lf_tmpl[LF_MAX_TMPL];      // N8: files made from a group's template
static int g_lf_virtual;            // N10: SSBU_LOOSE_TEMPLATE=3: such files are VIRTUAL records (no bytes of the archive)
static uint64_t g_ls_fidx, g_ls_flist; static uint32_t g_ls_nfold;          // the archive's own search folder tables (before the growth)
static void (*g_lf_log)(const char *);
static HookOrig g_lf_orig_inflate;
static CRITICAL_SECTION g_lf_lock;

static void lf_logf(const char *fmt, ...) {
    char line[900]; va_list ap; va_start(ap, fmt); vsnprintf(line, sizeof line, fmt, ap); va_end(ap);
    if (g_lf_log) g_lf_log(line);
}
static uint32_t lf_crc32(const char *s) {
    uint32_t c = 0xffffffffu;
    for (; *s; s++) { c ^= (uint8_t)*s; for (int k = 0; k < 8; k++) c = (c >> 1) ^ (0xedb88320u & (0u - (c & 1))); }
    return ~c;
}
static uint64_t lf_hash40(const char *s) { return ((uint64_t)(strlen(s) & 0xff) << 32) | lf_crc32(s); }
// a crc32 value moved behind `nbytes` more bytes (the linear part of crc32: what zlib's crc32_combine applies)
static uint32_t lf_crc_shift(uint32_t x, unsigned nbytes) {
    for (unsigned i = 0; i < nbytes * 8; i++) x = (x >> 1) ^ (0xedb88320u & (0u - (x & 1)));
    return x;
}
/* B3 (run b2sp2: the own motions of a new fighter never got their animation): a folder file whose name is only known
 * as a hash is written "0x<10 hex digits>.<ext>" (e.g. motion/body/c00/0x17383bb0de.nuanmb = hash40 of
 * "d03speciallwjump.nuanmb", extension included). The engine finds a motion's animation by FILE NAME hash inside the
 * motion folder, so the name hash of such a file is the hex value, not the hash of the text "0x...". -> the name hash,
 * 0 when the name is a plain name. */
static uint64_t lf_hex_name(const char *base) {
    if (base[0] != '0' || (base[1] != 'x' && base[1] != 'X')) return 0;
    uint64_t v = 0; int k = 2;
    for (; k < 12; k++) {
        char c = base[k]; int d = c >= '0' && c <= '9' ? c - '0' : c >= 'a' && c <= 'f' ? c - 'a' + 10 : c >= 'A' && c <= 'F' ? c - 'A' + 10 : -1;
        if (d < 0) return 0;
        v = (v << 4) | (uint64_t)d;
    }
    if (base[12] && base[12] != '.') return 0;
    return (v >> 32) ? v : 0;
}
/* hash40 of an archive path; a "0x<name hash>" last part is joined to its folder through the crc32 combination
 * (crc(A B) = shift(crc(A), len B) ^ crc(B)), so the path hash is the one of the real name */
static uint64_t lf_path_hash(const char *path) {
    const char *base = strrchr(path, '/');
    uint64_t nh = base ? lf_hex_name(base + 1) : 0;
    if (!nh) return lf_hash40(path);
    size_t pre = (size_t)(base + 1 - path); unsigned nlen = (unsigned)(nh >> 32);
    char tmp[512]; if (pre >= sizeof tmp) return lf_hash40(path);
    memcpy(tmp, path, pre); tmp[pre] = 0;
    uint32_t c = lf_crc_shift(lf_crc32(tmp), nlen) ^ (uint32_t)nh;
    return ((uint64_t)((pre + nlen) & 0xff) << 32) | c;
}
// hash40 of a folder path -> hash40 of the same text with "/" behind it (the form the file path rows keep their parent in)
static uint64_t lf_hash_slash(uint64_t h) {
    uint32_t s = ~(uint32_t)h ^ (uint32_t)'/';
    for (int k = 0; k < 8; k++) s = (s >> 1) ^ (0xedb88320u & (0u - (s & 1)));
    return ((uint64_t)((((h >> 32) & 0xff) + 1) & 0xff) << 32) | (uint32_t)~s;
}
// hash40 of a path that begins with `p` -> hash40 of the same path beginning with `p2` (the rest is not known)
static uint64_t lf_rename40(uint64_t h, const char *p, const char *p2) {
    unsigned len = (unsigned)(h >> 32) & 0xff, lp = (unsigned)strlen(p), lp2 = (unsigned)strlen(p2);
    uint32_t crc = (uint32_t)h ^ lf_crc_shift(lf_crc32(p) ^ lf_crc32(p2), len - lp);
    return ((uint64_t)((len - lp + lp2) & 0xff) << 32) | crc;
}
static int lf_readable(uint64_t a, size_t n) {
    MEMORY_BASIC_INFORMATION mi;
    if (a < 0x10000 || !VirtualQuery((void *)(uintptr_t)a, &mi, sizeof mi)) return 0;
    if (mi.State != MEM_COMMIT || (mi.Protect & (PAGE_NOACCESS | PAGE_GUARD))) return 0;
    return a + n <= (uint64_t)(uintptr_t)mi.BaseAddress + mi.RegionSize;
}
static uint64_t lf_r64(uint64_t a) { uint64_t v; memcpy(&v, (void *)(uintptr_t)a, 8); return v; }
static uint32_t lf_r32(uint64_t a) { uint32_t v; memcpy(&v, (void *)(uintptr_t)a, 4); return v; }
static void lf_w64(uint64_t a, uint64_t v) { memcpy((void *)(uintptr_t)a, &v, 8); }
static void lf_w32(uint64_t a, uint32_t v) { memcpy((void *)(uintptr_t)a, &v, 4); }

// ---------------------------------------------------------------- the folder scan
static int lf_json_str(const char *js, const char *key, char *out, size_t n) {
    char pat[48]; snprintf(pat, sizeof pat, "\"%s\"", key);
    const char *p = strstr(js, pat);
    out[0] = 0;
    if (!p) return 0;
    p += strlen(pat);
    while (*p == ' ' || *p == '\t' || *p == ':' || *p == '\r' || *p == '\n') p++;
    size_t k = 0;
    if (*p == '"') { for (p++; *p && *p != '"' && k + 1 < n; p++) out[k++] = *p; }
    out[k] = 0;
    return k > 0;
}
static int lf_token_char(char ch) { return (ch >= 'a' && ch <= 'z') || (ch >= '0' && ch <= '9'); }
// `path` (lower case) with every token `name` replaced by `donor`
static void lf_donor_path(const char *path, const char *name, const char *donor, char *out, size_t n) {
    size_t ln = strlen(name), k = 0;
    for (const char *p = path; *p && k + 40 < n; ) {
        if (strncmp(p, name, ln) == 0 && (p == path || !lf_token_char(p[-1])) && !lf_token_char(p[ln])) { k += (size_t)snprintf(out + k, n - k, "%s", donor); p += ln; }
        else out[k++] = *p++;
    }
    out[k] = 0;
}
static int lf_folder_find(uint64_t hash) {
    for (int i = 0; i < g_lf_folder_count; i++) if (g_lf_folder[i].hash == hash) return i;
    return -1;
}
static int lf_folder_put(uint64_t hash, uint64_t parent_hash, uint64_t name_hash, uint64_t donor_hash, int owner) {
    if (g_lf_folder_count >= LF_MAX_FOLDERS) return -1;
    LooseFolder *d = &g_lf_folder[g_lf_folder_count];
    memset(d, 0, sizeof *d);
    d->hash = hash; d->parent_hash = parent_hash; d->name_hash = name_hash; d->donor_hash = donor_hash; d->owner = owner;
    return g_lf_folder_count++;
}
// a folder of a new path given as text, parents first; -1 = the root
static int lf_add_folder(const char *path, int owner) {
    if (!path[0]) return -1;
    int at = lf_folder_find(lf_hash40(path));
    if (at >= 0) return at;
    if (strlen(path) >= 200) return -1;
    char parent[200], dpath[400]; snprintf(parent, sizeof parent, "%s", path);
    char *s = strrchr(parent, '/');
    if (s) *s = 0; else parent[0] = 0;
    lf_add_folder(parent, owner);
    const char *leaf = strrchr(path, '/'); leaf = leaf ? leaf + 1 : path;
    lf_donor_path(path, g_lf_owner[owner].name, g_lf_owner[owner].donor, dpath, sizeof dpath);
    return lf_folder_put(lf_hash40(path), parent[0] ? lf_hash40(parent) : 0, lf_hash40(leaf), strcmp(dpath, path) ? lf_hash40(dpath) : 0, owner);
}
// the renaming prefixes of a fighter folder: k = 0 "fighter/<name>", 1 "effect/fighter/<name>"
static void lf_prefix(int owner, int k, int donor, char *out, size_t n) {
    snprintf(out, n, k == 0 ? "fighter/%s" : "effect/fighter/%s", donor ? g_lf_owner[owner].donor : g_lf_owner[owner].name);
}
// is the archive's folder `fh` one of the donor prefixes of this owner, or below one? -> k, else -1 (the archive's own search folders)
static int lf_prefix_of(int owner, uint64_t fh) {
    uint64_t pre[LF_NPRE];
    for (int k = 0; k < LF_NPRE; k++) { char p[96]; lf_prefix(owner, k, 1, p, sizeof p); pre[k] = lf_hash40(p); }
    for (int depth = 0; depth < 16 && fh; depth++) {
        for (int k = 0; k < LF_NPRE; k++) if (pre[k] == fh) return k;
        int64_t lo = 0, hi = g_ls_nfold, at = -1;
        while (lo < hi) { int64_t mid = (lo + hi) / 2; uint64_t e = lf_r64(g_ls_fidx + 8ull * (uint64_t)mid), h = e & LF_MASK40; if (h == fh) { at = (int64_t)(e >> 40); break; } if (h < fh) lo = mid + 1; else hi = mid; }
        if (at < 0) return -1;
        fh = lf_r64(g_ls_flist + 0x20ull * (uint64_t)at + 8) & LF_MASK40;
    }
    return -1;
}
// the new folder for the donor's folder `dfh` (which is prefix k or below it), made with its parents; returns its hash, 0 = cannot
static uint64_t lf_folder_from_donor(int owner, uint64_t dfh, int k) {
    char p[96], p2[96]; lf_prefix(owner, k, 1, p, sizeof p); lf_prefix(owner, k, 0, p2, sizeof p2);
    if (dfh == lf_hash40(p)) return lf_add_folder(p2, owner) >= 0 ? lf_hash40(p2) : 0;
    uint64_t nh = lf_rename40(dfh, p, p2);
    if (lf_folder_find(nh) >= 0) return nh;
    int64_t lo = 0, hi = g_ls_nfold, at = -1;
    while (lo < hi) { int64_t mid = (lo + hi) / 2; uint64_t e = lf_r64(g_ls_fidx + 8ull * (uint64_t)mid), h = e & LF_MASK40; if (h == dfh) { at = (int64_t)(e >> 40); break; } if (h < dfh) lo = mid + 1; else hi = mid; }
    if (at < 0) return 0;
    uint64_t dparent = lf_r64(g_ls_flist + 0x20ull * (uint64_t)at + 8) & LF_MASK40, name = lf_r64(g_ls_flist + 0x20ull * (uint64_t)at + 16) & LF_MASK40;
    uint64_t nparent = lf_folder_from_donor(owner, dparent, k);
    if (!nparent) return 0;
    return lf_folder_put(nh, nparent, name, dfh, owner) >= 0 ? nh : 0;
}
// walk <dir>; `rel` = the archive path so far ("" at a fighter folder's top)
static void lf_scan(const char *dir, const char *rel, int owner) {
    char pat[MAX_PATH * 2]; WIN32_FIND_DATAA fd;
    snprintf(pat, sizeof pat, "%s\\*", dir);
    HANDLE h = FindFirstFileA(pat, &fd);
    if (h == INVALID_HANDLE_VALUE) return;
    do {
        if (fd.cFileName[0] == '.') continue;
        char sub[MAX_PATH * 2], r[MAX_PATH * 2];
        snprintf(sub, sizeof sub, "%s\\%s", dir, fd.cFileName);
        snprintf(r, sizeof r, "%s%s%s", rel, rel[0] ? "/" : "", fd.cFileName);
        /* N9: "src" at the top of a fighter's folder holds the fighter's script sources (fighter_sdk\tools\new_fighter.py): not archive content */
        if ((fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) && !rel[0] && !_stricmp(fd.cFileName, "src")) continue;
        if (fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) { lf_scan(sub, r, owner); continue; }
        if (g_lf_count >= LF_MAX) continue;
        size_t n = strlen(r);
        if (!strchr(r, '/')) continue;       // the top of a fighter's folder is not archive content (manifest, script DLL, lists)
        for (char *p = r; *p; p++) if (*p >= 'A' && *p <= 'Z') *p += 32;
        LooseFile *f = &g_lf[g_lf_count++];
        memset(f, 0, sizeof *f);
        f->arc_path = _strdup(r); f->disk_path = _strdup(sub);
        f->hash = ((uint64_t)(n & 0xff) << 32) | lf_crc32(r);
        { const char *bn = strrchr(r, '/'); f->name_hash = bn ? lf_hex_name(bn + 1) : 0; if (f->name_hash) f->hash = lf_path_hash(r); }   /* B3 */
        f->size = fd.nFileSizeLow; f->path_index = -1; f->owner = owner;
        if (owner >= 0) {
            char dp[MAX_PATH * 2];
            lf_donor_path(r, g_lf_owner[owner].name, g_lf_owner[owner].donor, dp, sizeof dp);
            f->donor_hash = strcmp(dp, r) ? lf_path_hash(dp) : 0;      /* B3: a "0x<name hash>" name joined to its folder */
            g_lf_owner[owner].files++;
        }
    } while (FindNextFileA(h, &fd));
    FindClose(h);
}
// clone_files.json of a fighter's folder: the hashes of files whose names are only known as hashes
static void lf_clone_list(const char *folder, int owner, int first) {
    char path[MAX_PATH * 2];
    snprintf(path, sizeof path, "%s\\clone_files.json", folder);
    FILE *fp = fopen(path, "rb");
    if (!fp) return;
    fseek(fp, 0, SEEK_END); long n = ftell(fp); fseek(fp, 0, SEEK_SET);
    char *js = malloc((size_t)n + 1);
    n = (long)fread(js, 1, (size_t)n, fp); js[n] = 0; fclose(fp);
    int listed = 0;
    for (char *p = strstr(js, "\"path\""); p; p = strstr(p + 1, "\"path\"")) {
        char *end = strchr(p, '}');
        if (!end) break;
        char keep = *end; *end = 0;
        char ap[400], dh[40], nh[40];
        if (lf_json_str(p, "path", ap, sizeof ap) && lf_json_str(p, "donor_hash", dh, sizeof dh) && lf_json_str(p, "new_hash", nh, sizeof nh)) {
            for (char *q = ap; *q; q++) if (*q >= 'A' && *q <= 'Z') *q += 32;
            for (int k = first; k < g_lf_count; k++)
                if (strcmp(g_lf[k].arc_path, ap) == 0) { g_lf[k].hash = strtoull(nh, NULL, 16); g_lf[k].donor_hash = strtoull(dh, NULL, 16); listed++; break; }
        }
        *end = keep;
    }
    free(js);
    lf_logf("[loose] %s: clone_files.json gives the path hash and the donor file of %d of its files", g_lf_owner[owner].name, listed);
}

// ---------------------------------------------------------------- the archive's in-memory tables
// 2026-10-16 (owner: menus and movies at 3 fps in the two-new-fighter build): this ran on EVERY decompress of the
// game's load thread with five VirtualQuery calls; a playing movie and the menus decompress all the time, and the
// queries contended with the renderer's GetWriteWatch for the process's address-space lock (log: ResInflateThread
// 19-35 ms per frame inside lf_readable / VirtualQuery, texture checks 16.8 ms per frame against 0.28 in the plain
// build). The chain service -> fsinfo -> pi -> arc belongs to objects that live for the whole run: once a chain has
// been checked, the next call for the same service only re-reads the same words (memory already proven readable) and
// takes the fast path while they are unchanged; any change of a link goes through the full check again.
typedef struct { uint64_t service, fsinfo, pi, arc; volatile LONG ok; } LfTablesMemo;
static LfTablesMemo g_lf_tmemo[4];
static int lf_tables(uint64_t service, uint64_t *fsinfo, uint64_t *arc) {
    for (int k = 0; k < 4; k++) {
        LfTablesMemo *m = &g_lf_tmemo[k];
        if (!m->ok || m->service != service) continue;
        uint64_t f = lf_r64(service ? service + 0xd0 : 0x7105331f20ull);
        if (f != m->fsinfo || lf_r64(f + 0x78) != m->pi || lf_r64(m->pi) != m->arc) break;
        if (!lf_r64(m->arc + 0x60) || !lf_r64(m->arc + 0x40)) return 0;
        *fsinfo = f; *arc = m->arc;
        return 1;
    }
    if (service) { if (!lf_readable(service + 0xd0, 8)) return 0; *fsinfo = lf_r64(service + 0xd0); }
    else { if (!lf_readable(0x7105331f20ull, 8)) return 0; *fsinfo = lf_r64(0x7105331f20ull); }
    if (!lf_readable(*fsinfo + 0x78, 8)) return 0;
    uint64_t pi = lf_r64(*fsinfo + 0x78);
    if (!lf_readable(pi, 16)) return 0;
    *arc = lf_r64(pi);
    if (!(lf_readable(*arc + 0xa0, 8) && lf_r64(*arc + 0x60) && lf_r64(*arc + 0x40))) return 0;
    {   /* remember the checked chain: the slot of this service, else a free one, else slot 0 */
        int k = 0;
        for (int j = 0; j < 4; j++) if (g_lf_tmemo[j].ok && g_lf_tmemo[j].service == service) { k = j; goto store; }
        for (int j = 0; j < 4; j++) if (!g_lf_tmemo[j].ok) { k = j; break; }
      store:
        InterlockedExchange(&g_lf_tmemo[k].ok, 0);
        g_lf_tmemo[k].service = service; g_lf_tmemo[k].fsinfo = *fsinfo; g_lf_tmemo[k].pi = pi; g_lf_tmemo[k].arc = *arc;
        InterlockedExchange(&g_lf_tmemo[k].ok, 1);
    }
    return 1;
}
static int64_t lf_find(uint64_t arc, uint64_t hash) {                // the game's own lookup: bucket, then the sorted range
    uint64_t buckets = lf_r64(arc + 0x50), entries = lf_r64(arc + 0x58);
    uint32_t nb = lf_r32(buckets + 4);
    if (!nb) return -1;
    uint64_t b = buckets + 8 + (hash % nb) * 8;
    uint32_t start = lf_r32(b), count = lf_r32(b + 4);
    for (uint32_t i = 0; i < count; i++) {
        uint64_t e = lf_r64(entries + 8ull * (start + i));
        if ((e & LF_MASK40) == hash) return (int64_t)(e >> 40);
    }
    return -1;
}
static int64_t lf_bsearch(uint64_t base, uint32_t n, uint64_t hash) {  // a sorted hash40 | index << 40 array: the index
    uint32_t lo = 0, hi = n;
    while (lo < hi) {
        uint32_t mid = lo + (hi - lo) / 2;
        uint64_t e = lf_r64(base + 8ull * mid), h = e & LF_MASK40;
        if (h == hash) return (int64_t)(e >> 40);
        if (h < hash) lo = mid + 1; else hi = mid;
    }
    return -1;
}
static int lf_cmp40(const void *a, const void *b) {
    uint64_t x = *(const uint64_t *)a & LF_MASK40, y = *(const uint64_t *)b & LF_MASK40;
    return x < y ? -1 : x > y;
}
static void *lf_grow_array(uint64_t old, size_t old_count, size_t add, size_t item) {
    uint8_t *p = VirtualAlloc(NULL, (old_count + add) * item + 64, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    if (p) memcpy(p, (void *)(uintptr_t)old, old_count * item);
    return p;
}

// The switch happens while the game runs: a thread that took a pointer into an old "loaded" array just before the
// switch (the inflate thread marks the file it is working on as loaded through such a pointer) still writes into the
// OLD array. The old arrays stay allocated, and for 10 seconds after the switch every row of them that changes is
// carried over into the new array (when the new row was not changed too).
static struct { uint8_t *old, *snap, *now; size_t count, item; long carried, conflicts; } g_lf_sync[2];
static struct { int array; uint32_t index; uint8_t snap[0x18]; } g_lf_pin[4096];
static int g_lf_pin_count;
static DWORD WINAPI lf_sync_thread(LPVOID arg) {
    (void)arg;
    for (int t = 0; t < 2500; t++) {
        for (int a = 0; a < 2; a++) {
            size_t item = g_lf_sync[a].item;
            if (memcmp(g_lf_sync[a].old, g_lf_sync[a].snap, g_lf_sync[a].count * item) == 0) continue;
            for (size_t i = 0; i < g_lf_sync[a].count; i++) {
                uint8_t *o = g_lf_sync[a].old + i * item, *s = g_lf_sync[a].snap + i * item, *n = g_lf_sync[a].now + i * item;
                if (memcmp(o, s, item) == 0) continue;
                if (memcmp(n, s, item) == 0) { memcpy(n, o, item); g_lf_sync[a].carried++; } else if (memcmp(n, o, item)) g_lf_sync[a].conflicts++;
                memcpy(s, o, item);
            }
        }
        Sleep(t < 2000 ? 1 : 16);
    }
    lf_logf("[loose] stage 2: writes into the old loaded tables after the switch, carried over in 10 s: %ld loaded-data rows (%ld conflicts), %ld loaded-file-path rows (%ld conflicts)",
            g_lf_sync[0].carried, g_lf_sync[0].conflicts, g_lf_sync[1].carried, g_lf_sync[1].conflicts);
    /* N7: the rows that were IN USE at the switch can have a pointer of a game object on their OLD copy for as long as
     * that object lives (it waits on the old row while the loader fills the new one, or the other way round). These
     * few rows are kept the same in both copies for the life of the process, in both directions. */
    if (!g_lf_pin_count) return 0;
    long both = 0, to_new = 0, to_old = 0, merged = 0;
    for (unsigned long t = 0; ; t++) {
        for (int k = 0; k < g_lf_pin_count; k++) {
            int a = g_lf_pin[k].array; size_t item = g_lf_sync[a].item, i = g_lf_pin[k].index;
            uint8_t *o = g_lf_sync[a].old + i * item, *n = g_lf_sync[a].now + i * item, *s = g_lf_pin[k].snap;
            int oc = memcmp(o, s, item) != 0, nc = memcmp(n, s, item) != 0;
            if (!oc && !nc) continue;
            if (oc && nc && memcmp(o, n, item)) {
                /* N8: BOTH copies changed since the last look (seen once per run in n8t3 / n8am: "1 changed in both").
                 * Taking one whole row loses the other side's write (a lost "loaded" state is a load that never
                 * ends). The row is merged FIELD by field: a field only one side changed is carried over; the user
                 * counter (loaded data + 8) takes both sides' changes; a field both changed: the new copy's. */
                static const uint8_t f0[] = { 0, 8, 12, 13, 14, 16, 24 }, f1[] = { 0, 4, 8 };
                const uint8_t *fl = a == 0 ? f0 : f1; int nf = a == 0 ? 6 : 2;
                both++;
                for (int q = 0; q < nf; q++) {
                    size_t b = fl[q], len = (size_t)fl[q + 1] - b;
                    int fo = memcmp(o + b, s + b, len) != 0, fn = memcmp(n + b, s + b, len) != 0;
                    if (fo && !fn) memcpy(n + b, o + b, len);
                    else if (fo && fn && a == 0 && b == 8) { uint32_t vo, vn, vs; memcpy(&vo, o + 8, 4); memcpy(&vn, n + 8, 4); memcpy(&vs, s + 8, 4); vn += vo - vs; memcpy(n + 8, &vn, 4); }
                }
                memcpy(o, n, item); memcpy(s, n, item); merged++;
                continue;
            }
            if (nc) { memcpy(o, n, item); to_old++; } else { memcpy(n, o, item); to_new++; }
            memcpy(s, n, item);
        }
        if (t == 30000 || t == 150000) lf_logf("[loose] stage 2: %d rows in use at the switch are kept the same in the old and the new tables: so far %ld changes carried old -> new, %ld new -> old, %ld changed in both (%ld merged field by field)",
                                g_lf_pin_count, to_new, to_old, both, merged);
        Sleep(2);
    }
    return 0;
}

// STAGE 2: rows for the fighter folders: a load group per fighter, rows for its files, search entries
static void lf_grow(uint64_t fsinfo, uint64_t arc) {
    uint64_t search = lf_r64(lf_r64(fsinfo + 0x78) + 8);
    uint64_t hdr = lf_r64(arc + 0x40), paths = lf_r64(arc + 0x60), ind = lf_r64(arc + 0x68), infos = lf_r64(arc + 0x90);
    uint64_t to_data = lf_r64(arc + 0x98), datas = lf_r64(arc + 0xa0), buckets = lf_r64(arc + 0x50), entries = lf_r64(arc + 0x58);
    uint64_t dirx = lf_r64(arc + 0x70), dirs = lf_r64(arc + 0x78);
    uint32_t n_path = lf_r32(hdr + 4), n_ind = lf_r32(hdr + 8), n_dir = lf_r32(hdr + 0xc), n_info = lf_r32(hdr + 0x18) + lf_r32(hdr + 0x28) + lf_r32(hdr + 0x44);
    uint32_t nb = lf_r32(buckets + 4), n_ent = lf_r32(buckets);
    uint64_t lfp = lf_r64(fsinfo + 8), ld = lf_r64(fsinfo + 0x10), ldir = lf_r64(fsinfo + 0x40);
    uint32_t n_lfp = lf_r32(fsinfo + 0x18), n_ld = lf_r32(fsinfo + 0x1c), n_ldir = lf_r32(fsinfo + 0x48);
    if (!lf_readable(search + 0x30, 8)) { lf_logf("[loose] stage 2: no search tables: NOT grown"); return; }
    uint64_t body = lf_r64(search + 8), fidx = lf_r64(search + 0x10), flist = lf_r64(search + 0x18), pidx = lf_r64(search + 0x20);
    uint64_t pli = lf_r64(search + 0x28), plist = lf_r64(search + 0x30);
    uint32_t n_fold = lf_r32(body), n_pli = lf_r32(body + 4), n_plist = lf_r32(body + 8);
    g_ls_fidx = fidx; g_ls_flist = flist; g_ls_nfold = n_fold;
    uint32_t use0 = lf_r32(fsinfo + 0x20), use1 = lf_r32(fsinfo + 0x24);
    lf_logf("[loose] stage 2: growth triggered by %s; rows in use at this moment: %u loaded file paths, %u loaded datas (0 / 0 = the game has not requested a file yet)",
            g_lf_early ? "the early poll (the tables had just been published)" : "the first decompress on the inflate thread (a file is in flight)", use0, use1);
    lf_logf("[loose] stage 2: tables before: %u file paths, %u file info indices, %u file infos (%u + %u + %u), %u hash entries in %u buckets, %u directories; loaded file paths %u, "
            "loaded datas %u, loaded directories %u; search: %u folders, %u path indices, %u paths", n_path, n_ind, n_info, lf_r32(hdr + 0x18), lf_r32(hdr + 0x28), lf_r32(hdr + 0x44), n_ent, nb, n_dir,
            n_lfp, n_ld, n_ldir, n_fold, n_pli, n_plist);
    if (n_lfp != n_path || n_ld != n_ind || n_ent != n_path || n_pli != n_plist || !lf_readable(infos + 16ull * n_info - 16, 16) || !lf_readable(ld + 0x18ull * n_ld - 0x18, 0x18)
        || !lf_readable(dirs + 0x34ull * n_dir - 0x34, 0x34) || !lf_readable(dirx + 8ull * n_dir - 8, 8)) {
        lf_logf("[loose] stage 2: the counts are not what the layout expects: NOT grown (new paths stay with the donor fallback)");
        return;
    }
    {   /* the renaming must give what hashing the text gives */
        uint64_t a = lf_rename40(lf_hash40("fighter/abcde/model/body/c00/x.bin"), "fighter/abcde", "fighter/zz9"), b = lf_hash40("fighter/zz9/model/body/c00/x.bin");
        if (a != b || lf_hash_slash(lf_hash40("fighter/zz9/model")) != lf_hash40("fighter/zz9/model/")) {
            lf_logf("[loose] stage 2: the hash renaming fails its self-test (%llx != %llx): NOT grown", (unsigned long long)a, (unsigned long long)b); return;
        }
        /* B3: a "0x<name hash>" file joined to its folder = the hash of the real path */
        char hx[32]; snprintf(hx, sizeof hx, "0x%010llx.nuanmb", (unsigned long long)lf_hash40("x.nuanmb"));
        char hp[96]; snprintf(hp, sizeof hp, "fighter/zz9/motion/body/c00/%s", hx);
        if (lf_path_hash(hp) != lf_hash40("fighter/zz9/motion/body/c00/x.nuanmb") || lf_hex_name(hx) != lf_hash40("x.nuanmb"))
            lf_logf("[loose] stage 2: the \"0x<name hash>\" path hash fails its self-test (%llx): hash-named new files will not be found", (unsigned long long)lf_path_hash(hp));
    }
    const char *genv = getenv("SSBU_LOOSE_GROUPS");
    int groups_on = !(genv && genv[0] == '0');
    /* SSBU_LOOSE_DIAG (diagnosis): 1 = the directory index is not switched (the groups are not findable), 2 = no renamed
     * files (they get private hashes), 4 = the group paths are not made search folders */
    int diag = getenv("SSBU_LOOSE_DIAG") ? atoi(getenv("SSBU_LOOSE_DIAG")) : 0;
    // ---- the plan: per fighter folder with files, its load group; then the loose files in no group
    int nn = 0, no_donor = 0;
    g_lf_plan_count = 0; g_lf_group_count = 0;
    static int8_t taken[LF_MAX];
    memset(taken, 0, sizeof taken);
    /* The groups are a work list: the costume group of every fighter folder with files is entered here; planning a
     * group's children (below) enters more groups: the directories of the donor's own tree that the group reaches
     * (its common group and what is below it), and a link row for every link row of the donor that leads there. */
    uint64_t fo = lf_r64(arc + 0x80), childh = lf_r64(arc + 0x88);
    uint32_t n_fo = lf_r32(hdr + 0x10) + lf_r32(hdr + 0x24) + lf_r32(hdr + 0x40), n_childh = lf_r32(hdr + 0x14);
    const char *tenv = getenv("SSBU_LOOSE_TREE");
    int tree_on = !(tenv && tenv[0] == '0');
    g_lf_child_count = 0; g_lf_fo_count = 0;
    for (int o = 0; o < g_lf_owner_count && groups_on; o++) {
        LooseOwner *ow = &g_lf_owner[o];
        if (!ow->files) continue;
        char dpath[96], npath[96], ppath[96];
        snprintf(dpath, sizeof dpath, "fighter/%s/c00", ow->donor); snprintf(npath, sizeof npath, "fighter/%s/c00", ow->name); snprintf(ppath, sizeof ppath, "fighter/%s", ow->name);
        int64_t dd = lf_bsearch(dirx, n_dir, lf_hash40(dpath));
        if (dd < 0) { lf_logf("[loose] stage 2: %s: the donor's %s is not a directory row: no group", ow->name, dpath); continue; }
        if (lf_bsearch(dirx, n_dir, lf_hash40(npath)) >= 0 || g_lf_group_count >= LF_MAX_GROUPS) continue;
        LooseGroup *g = &g_lf_group[g_lf_group_count];
        memset(g, 0, sizeof *g);
        g->hash = lf_hash40(npath); g->donor_hash = lf_hash40(dpath); g->parent_hash = lf_hash40(ppath); g->owner = o; g->donor_dir = (uint32_t)dd;
        g->dir_index = n_dir + (uint32_t)g_lf_group_count;
        snprintf(g->path, sizeof g->path, "%s", npath);
        g_lf_group_count++;
    }
    for (int gi = 0; gi < g_lf_group_count; gi++) {
        {
            LooseGroup *g = &g_lf_group[gi];
            int o = g->owner;
            LooseOwner *ow = &g_lf_owner[o];
            const char *npath = g->path, *dpath = "the donor's row";
            uint32_t dir_index = g->dir_index; int64_t dd = g->donor_dir;
            uint64_t drow = dirs + 0x34ull * (uint64_t)dd;
            uint32_t fs = lf_r32(drow + 0x20), fc = lf_r32(drow + 0x24);
            if (dir_index >= n_ldir || (*(uint8_t *)(uintptr_t)(ldir + 0x48ull * dir_index + 8) & 1) || fs + fc > n_info || g_lf_plan_count + (int)fc > LF_MAX_NEW * 2 || nn + (int)fc > LF_MAX_NEW) {
                lf_logf("[loose] stage 2: %s: no free loaded-directory row at %u (length %u) or its range %u..+%u does not fit: NOT grown", npath, dir_index, n_ldir, fs, fc);
                g_lf_group_count = 0; g_lf_plan_count = 0; return;
            }
            g->info_start = n_info + (uint32_t)g_lf_plan_count; g->count = g->is_link ? 0 : fc;
            if (g->is_link) fc = 0;
            int own = 0, brought = 0, renamed = 0, priv = 0, aliased = 0, alias_brought = 0;
            const char *ale = getenv("SSBU_LOOSE_ALIAS");
            int alias_on = !(ale && ale[0] == '0');
            /* N8: THE TEMPLATE of this group, for folder files that have no file of their own to be loaded from (a file
             * the donor never had; a shared file of the group that the folder brings): the smallest own, compressed,
             * non-regional file of the donor's range. Such a folder file becomes a new file of the group (kind 5) with
             * info-to-data and file-data rows OF ITS OWN (copies of the template's with the folder file's size): the
             * load thread unpacks the template's bytes into the new file's buffer and the hook then writes the folder's
             * file over it. SSBU_LOOSE_TEMPLATE=0: off (such files get no row / an alias). */
            const char *tpe = getenv("SSBU_LOOSE_TEMPLATE");
            uint32_t t_ii = LF_NONE, t_pi = 0, t_xi = 0, t_dec = 0xffffffffu;
            /* N9: OFF BY DEFAULT, SSBU_LOOSE_TEMPLATE=1 switches it on. Runs n9b2 (records in the middle of the range) and
             * n9b3 (ONE record appended at the end of the range): the costume group's load never ends - every file of the
             * range before the record is unpacked and served, then the loading screen runs for ever. The record's bytes
             * are the template's, at a place of the group's stretch the load thread has already passed (or not reached):
             * a record whose data is not at the next place of the stretch cannot be read by the GROUP load. The way on
             * is a record that the group load skips and a single-file request reads (its own seek), as the sound banks
             * are read: plan\phases\N9_checklist.md section 2. */
            /* N10, SSBU_LOOSE_TEMPLATE=3: THE VIRTUAL RECORD. Read in the inflate thread 0x71035444c0 [binary, 0x7103544b2c ..
             * 0x7103545468]: the bytes of a group are consumed SEQUENTIALLY - a running pointer (x24) is advanced by every
             * record's compressed size rounded up to 16 (0x7103545450), a record's offset (x20) only decides whether the
             * thread waits for the next read window ([service + 0x220] = the stretch position read so far). A record's
             * place in the archive is therefore never looked up: a template record (=1) made the pointer consume the
             * template's compressed size AGAIN, at the wrong place (runs n9b2, n9b3). A record with file-data
             * {offset 0, compressed size 0, flags 0 = stored raw, size = the folder file's} consumes nothing: the thread
             * allocates the buffer (0x7103544d18), "copies" at 0x7103545194 (the copy would read the folder file's size
             * from the running pointer: our copy hook does NOT run it for such a record and writes the folder's file) and
             * marks the file loaded (0x7103545438). Nothing of such a record refers to the archive's bytes. The template
             * is still used as the source of the path / indice / info row copies. */
            if (!tpe || !tpe[0]) tpe = "3";      /* N10: the default (0 = off: such files get no row / stay aliases; 1, 2 = the earlier, broken forms) */
            g_lf_virtual = tpe[0] == '3';
            for (uint32_t k = 0; k < fc && (tpe && (tpe[0] == '1' || tpe[0] == '2' || tpe[0] == '3')); k++) {
                uint64_t di = infos + 16ull * (fs + k);
                uint32_t dpi = lf_r32(di) & 0xffffffu, dxi = lf_r32(di + 4), fl = lf_r32(di + 12);
                if (dpi >= n_path || dxi >= n_ind || (lf_r32(ind + 8ull * dxi + 4) & 0xffffffu) != fs + k || (fl & 0x18000)) continue;
                uint64_t d = datas + 16ull * lf_r32(to_data + 12ull * lf_r32(di + 8) + 4);
                uint32_t comp = lf_r32(d + 4), dec = lf_r32(d + 8);
                if (!comp || comp >= dec || dec < 64 || dec >= t_dec) continue;
                t_dec = dec; t_ii = fs + k; t_pi = dpi; t_xi = dxi;
            }
            int tmpl_made = 0;
#define LF_TEMPLATE_NEW(q_, hash_) do { \
                LooseFile *tf_ = &g_lf[q_]; \
                char parent_[400]; snprintf(parent_, sizeof parent_, "%s", tf_->arc_path); *strrchr(parent_, '/') = 0; \
                int fa_ = lf_add_folder(parent_, o); \
                LooseNew *nw_ = &g_lf_new[nn]; \
                memset(nw_, 0, sizeof *nw_); \
                nw_->donor_pi = t_pi; nw_->donor_xi = t_xi; nw_->donor_ii = t_ii; nw_->owner = o; nw_->loose = (q_); nw_->kind = 5; nw_->hash = (hash_); \
                nw_->parent_hash = fa_ >= 0 ? g_lf_folder[fa_].hash : lf_hash40(parent_); nw_->info_pos = n_info + (uint32_t)g_lf_plan_count; \
                taken[q_] = 1; tmpl_made++; \
            } while (0)
            for (uint32_t k = 0; k < fc; k++) {
                uint64_t di = infos + 16ull * (fs + k);
                uint32_t dpi = lf_r32(di) & 0xffffffu, dxi = lf_r32(di + 4);
                g_lf_plan[g_lf_plan_count].donor_ii = fs + k; g_lf_plan[g_lf_plan_count].new_index = -1;
                if (dpi < n_path && dxi < n_ind && (lf_r32(ind + 8ull * dxi + 4) & 0xffffffu) == fs + k) {
                    /* the donor file's folder: the parent of its entry in the search path list (the folder's hash as the
                     * search tables keep it; the file path row keeps the parent with "/" behind it) */
                    uint64_t dh = lf_r64(paths + 0x20ull * dpi) & LF_MASK40, dparent = 0;
                    int64_t dsp = lf_bsearch(pidx, n_plist, dh);
                    if (dsp >= 0 && (uint32_t)dsp < n_pli) dparent = lf_r64(plist + 0x20ull * lf_r32(pli + 4ull * (uint64_t)dsp) + 8) & LF_MASK40;
                    LooseNew *nw = &g_lf_new[nn];
                    memset(nw, 0, sizeof *nw);
                    nw->donor_pi = dpi; nw->donor_xi = dxi; nw->donor_ii = fs + k; nw->owner = o; nw->loose = -1; nw->info_pos = n_info + (uint32_t)g_lf_plan_count;
                    for (int q = 0; q < g_lf_count; q++)
                        if (g_lf[q].owner == o && g_lf[q].path_index < 0 && g_lf[q].donor_hash == dh && !taken[q]) { nw->loose = q; break; }
                    int pk = dparent ? lf_prefix_of(o, dparent) : -1;
                    if (pk > 0 && (diag & 8)) pk = -1;
                    if (nw->loose >= 0) {
                        char parent[400]; snprintf(parent, sizeof parent, "%s", g_lf[nw->loose].arc_path);
                        *strrchr(parent, '/') = 0;
                        int fa = lf_add_folder(parent, o);
                        nw->kind = 1; nw->hash = g_lf[nw->loose].hash; nw->parent_hash = fa >= 0 ? g_lf_folder[fa].hash : lf_hash40(parent);
                        taken[nw->loose] = 1; brought++;
                    } else if (pk >= 0 && !(diag & 2)) {
                        char p[96], p2[96]; lf_prefix(o, pk, 1, p, sizeof p); lf_prefix(o, pk, 0, p2, sizeof p2);
                        nw->parent_hash = lf_folder_from_donor(o, dparent, pk);
                        if (nw->parent_hash) { nw->kind = 2; nw->hash = lf_rename40(dh, p, p2); renamed++; }
                    }
                    if (!nw->kind) {        /* a file of the group outside the fighter's own folders: a private hash (nobody asks for it by name) */
                        char salt[64]; snprintf(salt, sizeof salt, "own:%s", ow->name);
                        nw->kind = 3; nw->hash = (dh & 0xff00000000ull) | ((uint32_t)dh ^ lf_crc32(salt)); nw->parent_hash = 0; priv++;
                    }
                    g_lf_plan[g_lf_plan_count].new_index = nn++; own++;
                } else if (alias_on && dpi < n_path && dxi < n_ind) {
                    /* N8: A SHARED FILE OF THE GROUP (its indice row names a file info of another range: the shared
                     * stretch, or another directory) that lies under the donor's prefix gets an ALIAS: a new file path
                     * row with the renamed hash that leads to the DONOR's indice row (the same loaded-data row, the
                     * same bytes), and this file info carries the new path. The engine looks such files up by
                     * "<folder of the model>/<name written in the model file>" (0x71035c2040, hash -> file path
                     * index): without the alias the skeleton named by the fighter's own model file is not found and
                     * the model is null (run n7t2 / n8t3: reading address 0 in 0x7100491e00). */
                    uint64_t dh = lf_r64(paths + 0x20ull * dpi) & LF_MASK40, dparent = 0;
                    int64_t dsp = lf_bsearch(pidx, n_plist, dh);
                    if (dsp >= 0 && (uint32_t)dsp < n_pli) dparent = lf_r64(plist + 0x20ull * lf_r32(pli + 4ull * (uint64_t)dsp) + 8) & LF_MASK40;
                    int pk = dparent ? lf_prefix_of(o, dparent) : -1;
                    if (pk >= 0) {
                        char p[96], p2[96]; lf_prefix(o, pk, 1, p, sizeof p); lf_prefix(o, pk, 0, p2, sizeof p2);
                        uint64_t nh = lf_rename40(dh, p, p2), nparent = lf_folder_from_donor(o, dparent, pk);
                        int dup = 0;
                        for (int q = 0; q < nn; q++) if (g_lf_new[q].hash == nh) { dup = 1; break; }
                        int bq = -1;
                        for (int q = 0; q < g_lf_count; q++)
                            if (g_lf[q].owner == o && g_lf[q].path_index < 0 && g_lf[q].donor_hash == dh && !taken[q]) { bq = q; break; }
                        if (nparent && !dup && bq >= 0 && t_ii != LF_NONE && (g_lf_virtual || g_lf[bq].size >= t_dec)) {
                            /* the folder BRINGS this shared file: a file of its own through the group's template (kind 5).
                             * N9 (run n9b2: with the template record at THIS place of the range the load of the costume
                             * group stopped after its first file - the record's bytes are the template's, somewhere else
                             * in the group's stretch, and the load thread reads the stretch front to back): the shared
                             * row stays as it is (the donor's file under the donor's path, no alias) and the folder's
                             * file is appended with the other template files (taken = 3) */
                            (void)nh; taken[bq] = 3;
                        } else if (nparent && !dup) {
                            LooseNew *nw = &g_lf_new[nn];
                            memset(nw, 0, sizeof *nw);
                            nw->donor_pi = dpi; nw->donor_xi = dxi; nw->donor_ii = fs + k; nw->owner = o; nw->loose = -1; nw->info_pos = n_info + (uint32_t)g_lf_plan_count;
                            nw->kind = 4; nw->hash = nh; nw->parent_hash = nparent;
                            for (int q = 0; q < g_lf_count; q++)
                                if (g_lf[q].owner == o && g_lf[q].path_index < 0 && g_lf[q].donor_hash == dh && !taken[q]) { taken[q] = 2; alias_brought++; break; }
                            g_lf_plan[g_lf_plan_count].new_index = nn++; aliased++;
                        }
                    } else {
                        /* N9: A SHARED ROW OUTSIDE THE DONOR'S PREFIX THAT THE FOLDER BRINGS (the nine sound-bank files).
                         * Run n9ui2 (trace): the bank files are loaded through the rows of THESE records of the group's
                         * range - the donor's path rows went "in use, 2 users, loaded" while the rows of the fighter's
                         * own paths (stand-alone rows, found by the path lookup: `OWN FILE`) were never touched. So the
                         * record of the range itself must be the fighter's: a file of its own at this place (new path,
                         * new indice, new loaded rows) that shares the donor file's place in the archive; the single-
                         * file request the engine makes for such a record then fills OUR buffer and the decompress /
                         * copy hook writes the folder's file. SSBU_LOOSE_SOUNDROWS=1: on (default off). */
                        /* after run n9snd2 (six bank files served, one of them a replaced bank, fight reached, hash equal to
                         * the same run without these records): ON by default, SSBU_LOOSE_SOUNDROWS=0 switches it off */
                        static int srows = -1; if (srows < 0) { const char *se = getenv("SSBU_LOOSE_SOUNDROWS"); srows = !(se && se[0] == '0'); }
                        int bq = -1;
                        /* NOT for a regional / localized file (info flags 0x18000: one data row per region; the three
                         * "cheer" files of the voice set). Run n9snd made records for them too: two of the three ended in
                         * state 255, the third was never read, and the match load never ended. They stay shared records
                         * (the donor's files). */
                        int regional_file = (lf_r32(di + 12) & 0x18000) != 0;
                        for (int q = 0; q < g_lf_count && srows && !regional_file; q++)
                            if (g_lf[q].owner == o && g_lf[q].path_index < 0 && g_lf[q].donor_hash == dh && !taken[q]) { bq = q; break; }
                        if (bq >= 0 && nn < LF_MAX_NEW) {
                            char parent[400]; snprintf(parent, sizeof parent, "%s", g_lf[bq].arc_path);
                            *strrchr(parent, '/') = 0;
                            int fa = lf_add_folder(parent, o);
                            LooseNew *nw = &g_lf_new[nn];
                            memset(nw, 0, sizeof *nw);
                            nw->donor_pi = dpi; nw->donor_xi = dxi; nw->donor_ii = fs + k; nw->owner = o; nw->loose = bq; nw->info_pos = n_info + (uint32_t)g_lf_plan_count;
                            nw->kind = 1; nw->hash = g_lf[bq].hash; nw->parent_hash = fa >= 0 ? g_lf_folder[fa].hash : lf_hash40(parent);
                            taken[bq] = 1;
                            g_lf_plan[g_lf_plan_count].new_index = nn++;
                            lf_logf("[loose] stage 2: %s: a shared record of the group %s outside the donor's prefix that the folder brings: a record of the fighter's own at its place (file info %u)",
                                    g_lf[bq].arc_path, npath, nw->info_pos);
                        }
                    }
                }
                g_lf_plan_count++;
            }
            /* N8: FILES THE DONOR NEVER HAD: a folder file under "fighter/<name>/" whose donor path is not a file of the
             * archive is appended to the costume group's range as a file of its own made from the template */
            if (g->path[0] != '(' && !g->is_link && t_ii != LF_NONE) {
                char own_pre[96]; int lp = snprintf(own_pre, sizeof own_pre, "fighter/%s/", ow->name);
                for (int q = 0; q < g_lf_count && nn < LF_MAX_NEW && g_lf_plan_count < LF_MAX_NEW * 2; q++) {
                    LooseFile *f = &g_lf[q];
                    int shared_brought = taken[q] == 3;         /* N9: a shared file of the group that the folder brings (see above) */
                    if (f->owner != o || f->path_index >= 0 || (taken[q] && !shared_brought) || strncmp(f->arc_path, own_pre, (size_t)lp)) continue;
                    if (!shared_brought && f->donor_hash && lf_find(arc, f->donor_hash) >= 0) continue;
                    if (!g_lf_virtual && f->size < t_dec) { lf_logf("[loose] stage 2: %s (%u bytes): smaller than the group's template (%u bytes): NOT served", f->arc_path, f->size, t_dec); continue; }
                    LF_TEMPLATE_NEW(q, f->hash);
                    g_lf_plan[g_lf_plan_count].donor_ii = t_ii;
                    g_lf_plan[g_lf_plan_count].new_index = nn++;
                    g_lf_plan_count++; g->count++;
                    if (g_lf_virtual)
                        lf_logf("[loose] stage 2: %s (%u bytes): %s: a VIRTUAL record of its own at the end of the group %s (file info %u; no bytes of the archive: raw, compressed size 0)",
                                f->arc_path, f->size, shared_brought ? "a SHARED file of the donor's group that the folder brings" : "the donor has NO such file", npath, n_info + (uint32_t)g_lf_plan_count - 1);
                    else
                    lf_logf("[loose] stage 2: %s (%u bytes): the donor has NO such file: a file of its own in the group %s, loaded through the template (file info %u, %u bytes unpacked)",
                            f->arc_path, f->size, npath, t_ii, t_dec);
                }
            }
            if (tmpl_made) lf_logf("[loose] stage 2: GROUP %s: %d folder file(s) became files of their own through the group's template (file info %u); the range has %u file infos now", npath, tmpl_made, t_ii, g->count);
#undef LF_TEMPLATE_NEW
            ow->renamed += renamed; ow->private_rows += priv; ow->shared_rows += (int)fc - own;
            if (aliased || !g->is_link)
                lf_logf("[loose] stage 2: GROUP %s: %d of its %d shared rows lie under the donor's prefix and get an ALIAS path under the fighter's name (the donor's file, the donor's buffer; "
                        "%d of them are also in the folder: the folder's copy is NOT what the game gets for these)", npath, aliased, (int)fc - own, alias_brought);
            lf_logf("[loose] stage 2: GROUP %s (%llx) = directory row %u, a copy of %s (row %u, directory offset %u, flags %08x): %u file infos %u..: %d own files "
                    "(%d brought by the folder, %d renamed and filled with the donor's bytes, %d outside the fighter's folders under a private hash), %d shared rows copied",
                    npath, (unsigned long long)g->hash, dir_index, dpath, (uint32_t)dd, (uint32_t)(lf_r64(drow) >> 40), lf_r32(drow + 0x30), fc, g->info_start, own, brought, renamed, priv, (int)fc - own);
            // ---- the children of the donor's row: a child of the donor's own tree is cloned, any other is shared
            uint32_t cs = lf_r32(drow + 0x28), cc = lf_r32(drow + 0x2c) & 0xffff;
            g->child_start = cs; g->child_count = cc;
            if (g->is_link || cc > 31 || cs + cc > n_childh) continue;
            /* THE DONOR'S GROUP AS A DEPENDENCY (run n7a3: the engine asks for an article's model under the DONOR's path -
             * the article list is the donor's - and found the donor's file not loaded: reading address 0x20). The costume
             * group of a new fighter gets the donor's costume group as one more child, so the game loads both; the
             * donor's files answer every path the engine still builds with the donor's name. SSBU_LOOSE_DONOR_DEP=0: off. */
            const char *depe = getenv("SSBU_LOOSE_DONOR_DEP");
            int dep_on = g->path[0] != '(' && !(depe && depe[0] == '0');
            if ((!tree_on || !cc) && !dep_on) continue;
            char pre[96], pre2[96]; lf_prefix(o, 0, 1, pre, sizeof pre); lf_prefix(o, 0, 0, pre2, sizeof pre2);
            uint64_t ent[32]; int cloned = 0;
            for (uint32_t k = 0; k < cc; k++) {
                uint64_t q = lf_r64(childh + 8ull * (cs + k));
                uint32_t ci = (uint32_t)(q >> 40);
                ent[k] = q;
                if (ci >= n_dir || !tree_on) continue;
                uint64_t crow = dirs + 0x34ull * ci;
                uint32_t cflags = lf_r32(crow + 0x30), target = ci;
                int link = (cflags & 0x10000000u) != 0;
                if (link) {
                    uint32_t cfo = (uint32_t)(lf_r64(crow) >> 40);
                    if (cfo >= n_fo) continue;
                    target = lf_r32(fo + 0x1cull * cfo + 0x18);
                    if (target >= n_dir) continue;
                }
                /* is the target a directory of the donor's own tree ("fighter/<donor>" is one of its parents)? */
                int under = 0; uint32_t walk = target;
                for (int depth = 0; depth < 8; depth++) {
                    uint64_t ph = lf_r64(dirs + 0x34ull * walk + 0x10) & LF_MASK40;
                    if (ph == lf_hash40(pre)) { under = 1; break; }
                    int64_t up = lf_bsearch(dirx, n_dir, ph);
                    if (up < 0) break;
                    walk = (uint32_t)up;
                }
                if (!under) continue;
                /* the clone of the target (made once) */
                int tg = -1;
                for (int x = 0; x < g_lf_group_count; x++) if (g_lf_group[x].owner == o && !g_lf_group[x].is_link && g_lf_group[x].donor_dir == target) tg = x;
                if (tg < 0) {
                    if (g_lf_group_count + 2 > LF_MAX_GROUPS) continue;
                    uint64_t th = lf_r64(dirs + 0x34ull * target) & LF_MASK40, tp = lf_r64(dirs + 0x34ull * target + 0x10) & LF_MASK40;
                    LooseGroup *ng = &g_lf_group[g_lf_group_count];
                    memset(ng, 0, sizeof *ng);
                    ng->hash = lf_rename40(th, pre, pre2); ng->donor_hash = th; ng->owner = o; ng->donor_dir = target;
                    ng->parent_hash = tp == lf_hash40(pre) ? lf_hash40(pre2) : lf_rename40(tp, pre, pre2);
                    ng->dir_index = n_dir + (uint32_t)g_lf_group_count;
                    snprintf(ng->path, sizeof ng->path, "(directory %llx of %s, the donor's %llx)", (unsigned long long)ng->hash, ow->name, (unsigned long long)th);
                    tg = g_lf_group_count++;
                    g = &g_lf_group[gi];
                }
                if (!link) { ent[k] = g_lf_group[tg].hash | ((uint64_t)g_lf_group[tg].dir_index << 40); cloned++; continue; }
                /* a link row of the donor that leads into its own tree: a link row of our own, with a directory-offset
                 * row of its own whose target is the clone */
                if (g_lf_fo_count >= LF_MAX_GROUPS || g_lf_group_count >= LF_MAX_GROUPS) continue;
                LooseGroup *lg = &g_lf_group[g_lf_group_count];
                memset(lg, 0, sizeof *lg);
                lg->is_link = 1; lg->owner = o; lg->donor_dir = ci; lg->donor_hash = lf_r64(crow) & LF_MASK40;
                lg->hash = lf_rename40(lg->donor_hash, pre, pre2); lg->parent_hash = g->hash;
                lg->dir_index = n_dir + (uint32_t)g_lf_group_count;
                lg->fo_new = n_fo + (uint32_t)g_lf_fo_count; lg->fo_src = (uint32_t)(lf_r64(crow) >> 40); lg->fo_target = g_lf_group[tg].dir_index;
                g_lf_fo_count++;
                snprintf(lg->path, sizeof lg->path, "(link %llx of %s -> directory row %u)", (unsigned long long)lg->hash, ow->name, lg->fo_target);
                ent[k] = lg->hash | ((uint64_t)lg->dir_index << 40); cloned++;
                g_lf_group_count++;
            }
            if (dep_on) ent[cc] = g->donor_hash | ((uint64_t)g->donor_dir << 40);
            if ((cloned || dep_on) && g_lf_child_count + (int)cc + dep_on <= LF_MAX_GROUPS * 8) {
                g->child_start = n_childh + (uint32_t)g_lf_child_count; g->child_count = cc + (uint32_t)dep_on;
                memcpy(&g_lf_child[g_lf_child_count], ent, 8ull * g->child_count); g_lf_child_count += (int)g->child_count;
                lf_logf("[loose] stage 2: GROUP %s: %u children of the donor's row, %d of them clones of the donor's own tree%s (new child list at %u)", npath, cc, cloned,
                        dep_on ? "; + the DONOR'S GROUP as a dependency (its files answer paths the engine builds with the donor's name)" : "", g->child_start);
            }
        }
    }
    int standalone = 0, no_group = 0;
    for (int k = 0; k < g_lf_count; k++) {
        LooseFile *f = &g_lf[k];
        if (f->path_index >= 0 || f->owner < 0 || taken[k]) continue;
        int64_t d = f->donor_hash ? lf_find(arc, f->donor_hash) : -1;
        if (d < 0) { no_donor++; lf_logf("[loose] %s (%u bytes): not in the archive and no donor file (%llx): NOT served", f->arc_path, f->size, (unsigned long long)f->donor_hash); continue; }
        if (nn >= LF_MAX_NEW || g_lf_plan_count >= LF_MAX_NEW * 2) break;
        {   /* N7: a file row without a group is never read when the game expects the file from a group (N6 runs a3, b1),
             * and the donors of these files come with the SHARED stretch of the donor's group (the second directory-offset
             * row, which the new group shares) or by a request of their own. Until the shared stretch has rows of its own
             * these files get NO row: the path under the new name is answered by the registry's donor fallback.
             * SSBU_LOOSE_STANDALONE=1 adds the row all the same (N6's form). */
            static int alone = -1; if (alone < 0) { const char *se = getenv("SSBU_LOOSE_STANDALONE"); alone = se && se[0] == '1'; }
            /* N9: the picture files of the roster row ("ui/...") are always asked singly: a row of its own by default */
            if (!alone && strncmp(f->arc_path, "ui/", 3)) {
                uint32_t dxi0 = (uint32_t)(lf_r64(paths + 0x20ull * (uint64_t)d) >> 40), dii0 = lf_r32(ind + 8ull * dxi0 + 4) & 0xffffffu;
                lf_logf("[loose] stage 2: %s (%u bytes): its donor file (file info %u) is not an own file of a group of %s (the shared stretch of the donor's group, or a file requested "
                        "singly): NO row, the DONOR FALLBACK answers this path", f->arc_path, f->size, dii0, g_lf_owner[f->owner].name);
                no_group++;
                continue;
            }
        }
        char parent[400]; snprintf(parent, sizeof parent, "%s", f->arc_path);
        *strrchr(parent, '/') = 0;
        int fa = lf_add_folder(parent, f->owner);
        LooseNew *nw = &g_lf_new[nn];
        memset(nw, 0, sizeof *nw);
        nw->donor_pi = d; nw->donor_xi = (uint32_t)(lf_r64(paths + 0x20ull * (uint64_t)d) >> 40); nw->donor_ii = lf_r32(ind + 8ull * nw->donor_xi + 4) & 0xffffffu;
        nw->owner = f->owner; nw->loose = k; nw->kind = 1; nw->hash = f->hash; nw->parent_hash = fa >= 0 ? g_lf_folder[fa].hash : lf_hash40(parent);
        nw->info_pos = n_info + (uint32_t)g_lf_plan_count;
        g_lf_plan[g_lf_plan_count].donor_ii = nw->donor_ii; g_lf_plan[g_lf_plan_count].new_index = nn++;
        g_lf_plan_count++; standalone++;
        if (standalone <= 12) lf_logf("[loose] stage 2: %s: its donor file is in no group of %s: a file row without a group", f->arc_path, g_lf_owner[f->owner].name);
    }
    if (!nn) { lf_logf("[loose] stage 2: no new paths"); return; }
    int n_group = g_lf_group_count, n_newinfo = g_lf_plan_count;
    // the group paths as folders of the search tables (when the donor's is one)
    for (int g = 0; g < n_group && !(diag & 4); g++)
        if (g_lf_group[g].path[0] != '(' && lf_bsearch(fidx, n_fold, g_lf_group[g].donor_hash) >= 0) lf_add_folder(g_lf_group[g].path, g_lf_group[g].owner);
    // the folders of the new paths: which of them the search tables already have
    int new_fold = 0;
    for (int i = 0; i < g_lf_folder_count; i++) {
        LooseFolder *d = &g_lf_folder[i];
        int64_t at = lf_bsearch(fidx, n_fold, d->hash);
        d->exists = at >= 0;
        d->fpos = d->exists ? (uint32_t)at : n_fold + (uint32_t)new_fold++;
    }
    for (int i = 0; i < g_lf_folder_count; i++) {
        LooseFolder *d = &g_lf_folder[i];
        int pq = lf_folder_find(d->parent_hash);
        if (!d->exists && (pq < 0 || g_lf_folder[pq].exists))
            lf_logf("[loose] stage 2: new search folder %llx (name %llx, donor's %llx) becomes a child of the archive's folder %llx", (unsigned long long)d->hash, (unsigned long long)d->name_hash,
                    (unsigned long long)d->donor_hash, (unsigned long long)d->parent_hash);
    }
    {   /* how many new files each new folder gets */
        char line[800]; int k = 0; line[0] = 0;
        for (int i = 0; i < g_lf_folder_count && k < 740; i++) {
            if (g_lf_folder[i].exists) continue;
            int cnt = 0, cnt2 = 0;
            for (int j = 0; j < nn; j++) if (g_lf_new[j].parent_hash == g_lf_folder[i].hash) { cnt++; cnt2 += g_lf_new[j].kind == 2; }
            k += snprintf(line + k, sizeof line - k, " %llx:%d(%d)", (unsigned long long)g_lf_folder[i].hash, cnt, cnt2);
        }
        lf_logf("[loose] stage 2: new search folders, files (of them renamed):%s", line);
    }
    int n_sfile = 0;
    for (int j = 0; j < nn; j++) if (g_lf_new[j].kind != 3) n_sfile++;
    uint32_t add_p = (uint32_t)(n_sfile + new_fold);
    uint8_t *paths2 = lf_grow_array(paths, n_path, (size_t)nn, 0x20), *ind2 = lf_grow_array(ind, n_ind, (size_t)nn, 8), *infos2 = lf_grow_array(infos, n_info, (size_t)n_newinfo, 16);
    uint8_t *lfp2 = lf_grow_array(lfp, n_lfp, (size_t)nn, 8), *ld2 = lf_grow_array(ld, n_ld, (size_t)nn, 0x18);
    uint8_t *ent2 = VirtualAlloc(NULL, ((size_t)n_ent + nn) * 8 + 64, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    uint8_t *buck2 = lf_grow_array(buckets, (size_t)nb + 1, 0, 8);
    uint8_t *dirs2 = lf_grow_array(dirs, n_dir, (size_t)n_group, 0x34), *dirx2 = lf_grow_array(dirx, n_dir, (size_t)n_group, 8);
    uint8_t *fo2 = lf_grow_array(fo, n_fo, (size_t)g_lf_fo_count + 1, 0x1c), *childh2 = lf_grow_array(childh, n_childh, (size_t)g_lf_child_count + 1, 8);
    if (!fo2 || !childh2) { lf_logf("[loose] stage 2: no memory: NOT grown"); return; }
    memcpy(childh2 + 8ull * n_childh, g_lf_child, 8ull * (size_t)g_lf_child_count);
    uint8_t *flist2 = lf_grow_array(flist, n_fold, (size_t)new_fold, 0x20), *fidx2 = lf_grow_array(fidx, n_fold, (size_t)new_fold, 8);
    uint8_t *plist2 = lf_grow_array(plist, n_plist, add_p, 0x20), *pli2 = lf_grow_array(pli, n_pli, add_p, 4), *pidx2 = lf_grow_array(pidx, n_plist, add_p, 8);
    if (!paths2 || !ind2 || !infos2 || !lfp2 || !ld2 || !ent2 || !buck2 || !dirs2 || !dirx2 || !flist2 || !fidx2 || !plist2 || !pli2 || !pidx2) { lf_logf("[loose] stage 2: no memory: NOT grown"); return; }
#define P64(base, off) (*(uint64_t *)((base) + (off)))
#define P32(base, off) (*(uint32_t *)((base) + (off)))
    // ---- file infos in the planned order: a new file's row, or the donor's row as it is
    int raised = 0, regional = 0, n_tmpl = 0;
    uint32_t n_i2d = lf_r32(hdr + 0x1c) + lf_r32(hdr + 0x28) + lf_r32(hdr + 0x50), n_datas = lf_r32(hdr + 0x20) + lf_r32(hdr + 0x28) + lf_r32(hdr + 0x54);
    for (int q = 0; q < n_newinfo; q++) {
        memcpy(infos2 + 16ull * (n_info + (uint32_t)q), (void *)(uintptr_t)(infos + 16ull * g_lf_plan[q].donor_ii), 16);
        if (g_lf_plan[q].new_index < 0) continue;
        int j = g_lf_plan[q].new_index;
        LooseNew *nw = &g_lf_new[j];
        LooseFile *f = nw->loose >= 0 ? &g_lf[nw->loose] : NULL;
        uint32_t pi = n_path + (uint32_t)j, xi = n_ind + (uint32_t)j, ii = n_info + (uint32_t)q;
        uint32_t dxi = nw->donor_xi, dii_raw = lf_r32(ind + 8ull * dxi + 4);
        const uint8_t *dp = (const uint8_t *)(uintptr_t)(paths + 0x20ull * (uint64_t)nw->donor_pi);
        const uint8_t *di = (const uint8_t *)(uintptr_t)(infos + 16ull * nw->donor_ii);
        uint8_t *np = paths2 + 0x20ull * pi;
        memcpy(np, dp, 0x20);
        P64(np, 0) = nw->hash | ((uint64_t)xi << 40);
        if (nw->parent_hash) P64(np, 16) = lf_hash_slash(nw->parent_hash) | (P64(dp, 16) & ~LF_MASK40);       /* kind 3 keeps the donor's parent */
        if (nw->kind == 4) {        /* N8, an alias: the new path leads to the DONOR's indice row; the indice / loaded-data rows at xi stay unused */
            P64(np, 0) = nw->hash | ((uint64_t)dxi << 40);
            P32(ind2, 8ull * xi) = lf_r32(ind + 8ull * dxi); P32(ind2, 8ull * xi + 4) = dii_raw;
            uint8_t *ai = infos2 + 16ull * ii;
            P32(ai, 0) = pi | (P32(di, 0) & 0xff000000u);                                           /* the indice index stays the donor's */
            memset(ld2 + 0x18ull * xi, 0, 0x18);
            P32(lfp2, 8ull * pi) = lf_r32(lfp + 8ull * (uint64_t)nw->donor_pi); P32(lfp2, 8ull * pi + 4) = 0;
            continue;
        }
        /* a file info indice row: +4 = file info index in the low 24 bits, flags in the top byte: the donor's flags */
        P32(ind2, 8ull * xi) = lf_r32(ind + 8ull * dxi); P32(ind2, 8ull * xi + 4) = ii | (dii_raw & 0xff000000u);
        uint8_t *ni = infos2 + 16ull * ii;
        P32(ni, 0) = pi | (P32(di, 0) & 0xff000000u); P32(ni, 4) = xi;
        /* loaded rows: not in use (the game's directory set-up and 0x710353ff00 fill them on first use) */
        memset(ld2 + 0x18ull * xi, 0, 0x18);
        P32(lfp2, 8ull * pi) = lf_r32(lfp + 8ull * (uint64_t)nw->donor_pi) == dxi ? xi : 0; P32(lfp2, 8ull * pi + 4) = 0;
        uint32_t flags = P32(di, 12), itd = P32(di, 8), data_index = lf_r32(to_data + 12ull * itd + 4);
        uint64_t d = datas + 16ull * data_index;
        if (flags & 0x18000) regional++;
        if (f && nw->kind == 5 && n_tmpl < LF_MAX_TMPL) {
            /* N8, a file made from the group's template: info-to-data and file-data rows of its own (written below,
             * behind the archive's), the folder file's own name and extension in its rows */
            const char *base = strrchr(f->arc_path, '/'), *ext = strrchr(f->arc_path, '.');
            base = base ? base + 1 : f->arc_path;
            P64(np, 24) = (f->name_hash ? f->name_hash : lf_hash40(base)) | (P64(dp, 24) & ~LF_MASK40);   /* B3: a "0x<name hash>" file: the hash itself */
            if (ext && ext > base) P64(np, 8) = lf_hash40(ext + 1) | (P64(dp, 8) & ~LF_MASK40);
            P32(ni, 8) = n_i2d + (uint32_t)n_tmpl;
            /* N9, SSBU_LOOSE_TEMPLATE=2: the record gets the info flags of the group's SHARED records (0x00300010 [data]:
             * the group load skips such a record and the engine reads it by a single-file request, which seeks to the
             * record's own bytes - run n9snd showed the engine making that request for records of a new group's range).
             * With the flags of the template (=1) the group load itself tries to read the record and never ends. */
            { const char *t2 = getenv("SSBU_LOOSE_TEMPLATE"); if (t2 && t2[0] == '2') P32(ni, 12) = 0x00300010u; }
            g_lf_tmpl[n_tmpl].itd = itd; g_lf_tmpl[n_tmpl].data_index = data_index; g_lf_tmpl[n_tmpl].size = f->size > lf_r32(d + 8) ? f->size : lf_r32(d + 8);
            g_lf_tmpl[n_tmpl].info = ii;
            if (g_lf_virtual) {
                /* N10: info flags = the buffer's alignment only (low 15 bits [binary 0x7103544b30]; 0 = the archive's
                 * default): 0x1000 for a texture / effect container (what the archive's own records of these types
                 * carry; reference\ARCropolis sets the same bit for them), else the template's; not regional, not a
                 * redirect, no bit 20 */
                const char *e5 = ext && ext > base ? ext + 1 : "";
                P32(ni, 12) = (!strcmp(e5, "nutexb") || !strcmp(e5, "eff")) ? 0x1000u : (flags & 0x7fffu);
                g_lf_tmpl[n_tmpl].size = f->size;
            }
            f->path_index = (int32_t)pi; f->indice_index = xi; f->info_index = ii; f->is_new = 2; f->data_index = n_datas + (uint32_t)n_tmpl;
            f->arc_size = g_lf_tmpl[n_tmpl].size;
            g_lf_owner[f->owner].new_files++;
            n_tmpl++;
        } else if (f) {
            f->path_index = (int32_t)pi; f->indice_index = xi; f->info_index = ii; f->is_new = 1; f->data_index = data_index;
            f->arc_size = lf_r32(d + 8);
            if (!(flags & 0x18000) && f->size > f->arc_size) { lf_w32(d + 8, f->size); raised++; }
            g_lf_owner[f->owner].new_files++;
        }
        if (j < 2) lf_logf("[loose] stage 2: row %d (%s, kind %d): donor file path 0x%llx, indice 0x%x (flags byte %02x), info 0x%x (flags %08x, info-to-data 0x%x) -> path 0x%x, indice 0x%x, info 0x%x",
                           j, f ? f->arc_path : "a renamed file", nw->kind, (unsigned long long)nw->donor_pi, dxi, dii_raw >> 24, nw->donor_ii, flags, itd, pi, xi, ii);
    }
    // ---- N8: the info-to-data and file-data rows of the files made from a template (after the size raises above)
    uint8_t *to_data2 = NULL, *datas2 = NULL;
    if (n_tmpl) {
        to_data2 = lf_grow_array(to_data, n_i2d, (size_t)n_tmpl, 12); datas2 = lf_grow_array(datas, n_datas, (size_t)n_tmpl, 16);
        if (!to_data2 || !datas2) { lf_logf("[loose] stage 2: no memory: NOT grown"); return; }
        for (int e = 0; e < n_tmpl; e++) {
            memcpy(to_data2 + 12ull * (n_i2d + (uint32_t)e), (void *)(uintptr_t)(to_data + 12ull * g_lf_tmpl[e].itd), 12);
            P32(to_data2, 12ull * (n_i2d + (uint32_t)e) + 4) = n_datas + (uint32_t)e;
            /* N9, SSBU_LOOSE_TEMPLATE=2: [data: a donor group's range] the records the engine reads singly (flags
             * 0x00300010) have load type 0 in the top byte of this row's third word; a group's own files have 1 */
            { const char *t2 = getenv("SSBU_LOOSE_TEMPLATE"); if (t2 && t2[0] == '2') to_data2[12ull * (n_i2d + (uint32_t)e) + 11] = 0; }
            memcpy(datas2 + 16ull * (n_datas + (uint32_t)e), (void *)(uintptr_t)(datas + 16ull * g_lf_tmpl[e].data_index), 16);
            P32(datas2, 16ull * (n_datas + (uint32_t)e) + 8) = g_lf_tmpl[e].size;
            if (g_lf_virtual) {     /* N10: {offset 0, compressed size 0, size, flags 0 = raw}; the info-to-data row names its own file info, load type 1 (a group's own file) */
                P32(datas2, 16ull * (n_datas + (uint32_t)e)) = 0; P32(datas2, 16ull * (n_datas + (uint32_t)e) + 4) = 0; P32(datas2, 16ull * (n_datas + (uint32_t)e) + 12) = 0;
                P32(to_data2, 12ull * (n_i2d + (uint32_t)e) + 8) = (g_lf_tmpl[e].info & 0xffffffu) | 0x01000000u;
            }
        }
        lf_logf("[loose] stage 2: %d file(s) made from a template: info-to-data rows %u -> %u, file-data rows %u -> %u (each with the folder file's size)", n_tmpl, n_i2d, n_i2d + (uint32_t)n_tmpl,
                n_datas, n_datas + (uint32_t)n_tmpl);
    }
    // ---- the directory rows of the groups
    for (int g = 0; g < n_group; g++) {
        LooseGroup *gr = &g_lf_group[g];
        const uint8_t *dr = (const uint8_t *)(uintptr_t)(dirs + 0x34ull * gr->donor_dir);
        uint8_t *nr = dirs2 + 0x34ull * gr->dir_index;
        memcpy(nr, dr, 0x34);
        P64(nr, 0) = gr->hash | (P64(dr, 0) & ~LF_MASK40);           /* the donor's directory-offset row: the same stretch of the archive */
        P64(nr, 16) = gr->parent_hash | (P64(dr, 16) & ~LF_MASK40);
        if (gr->is_link) {                                           /* a link row: its own directory-offset row, whose target is the clone */
            uint8_t *nf = fo2 + 0x1cull * gr->fo_new;
            memcpy(nf, (void *)(uintptr_t)(fo + 0x1cull * gr->fo_src), 0x1c);
            P32(nf, 0x18) = gr->fo_target;
            P64(nr, 0) = gr->hash | ((uint64_t)gr->fo_new << 40);
        } else {
            P32(nr, 0x20) = gr->info_start;
            P32(nr, 0x24) = gr->count;                               /* N8: the donor's count + the files the donor never had */
            P32(nr, 0x28) = gr->child_start;
            P32(nr, 0x2c) = (P32(dr, 0x2c) & 0xffff0000u) | (gr->child_count & 0xffffu);
        }
        P64(dirx2, 8ull * gr->dir_index) = gr->hash | ((uint64_t)gr->dir_index << 40);
    }
    qsort(dirx2, (size_t)n_dir + (size_t)n_group, 8, lf_cmp40);
    // ---- hash -> file path index, per bucket, sorted
    {
        uint64_t *add = malloc((size_t)nn * 8); uint32_t *addb = malloc((size_t)nn * 4);
        for (int j = 0; j < nn; j++) { add[j] = g_lf_new[j].hash | ((uint64_t)(n_path + (uint32_t)j) << 40); addb[j] = (uint32_t)(g_lf_new[j].hash % nb); }
        uint32_t out = 0;
        for (uint32_t b = 0; b < nb; b++) {
            uint32_t start = lf_r32(buckets + 8 + 8ull * b), count = lf_r32(buckets + 12 + 8ull * b), first = out;
            memcpy(ent2 + 8ull * out, (void *)(uintptr_t)(entries + 8ull * start), 8ull * count); out += count;
            int extra = 0;
            for (int j = 0; j < nn; j++) if (addb[j] == b) { P64(ent2, 8ull * out) = add[j]; out++; extra++; }
            if (extra) qsort(ent2 + 8ull * first, out - first, 8, lf_cmp40);
            P32(buck2, 8 + 8ull * b) = first; P32(buck2, 12 + 8ull * b) = out - first;
        }
        P32(buck2, 0) = out;
        free(add); free(addb);
    }
    // ---- search tables: folders the archive does not have, then the files; each entry linked into its parent's child list
    uint32_t k_path = 0;
#define LF_LINK(parent_hash_, ipos, next_out) do { \
        next_out = LF_NONE; \
        int64_t at_ = -1; \
        int q_ = lf_folder_find(parent_hash_); \
        if (q_ >= 0) at_ = g_lf_folder[q_].fpos; \
        if (at_ < 0) at_ = lf_bsearch(fidx, n_fold, (parent_hash_)); \
        if (at_ >= 0) { uint8_t *pe_ = flist2 + 0x20ull * (uint64_t)at_; next_out = P32(pe_, 24) & 0xffffffu; \
            P32(pe_, 24) = (P32(pe_, 24) & 0xff000000u) | (ipos); P64(pe_, 8) += 1ull << 40; } \
    } while (0)
    int cloned_folders = 0;
    for (int i = 0; i < g_lf_folder_count; i++) {
        LooseFolder *d = &g_lf_folder[i];
        if (d->exists) continue;
        uint64_t dh = d->donor_hash;
        int64_t dat = dh ? lf_bsearch(fidx, n_fold, dh) : -1, dpat = dh ? lf_bsearch(pidx, n_plist, dh) : -1;
        uint8_t *fe = flist2 + 0x20ull * d->fpos;
        memset(fe, 0, 0x20);
        if (dat >= 0) { memcpy(fe, (void *)(uintptr_t)(flist + 0x20ull * (uint64_t)dat), 0x20); cloned_folders++; }
        P64(fe, 0) = d->hash | ((uint64_t)LF_NONE << 40);
        P64(fe, 8) = d->parent_hash;                                     /* child count 0: raised by every link */
        P64(fe, 16) = d->name_hash | (P64(fe, 16) & ~LF_MASK40);
        P32(fe, 24) = (P32(fe, 24) & 0xff000000u) | LF_NONE;
        P64(fidx2, 8ull * d->fpos) = d->hash | ((uint64_t)d->fpos << 40);
        // the folder as an entry of the path list
        uint32_t ipos = n_pli + k_path, ppos = n_plist + k_path, next;
        d->ipos = ipos;
        uint8_t *pe = plist2 + 0x20ull * ppos;
        memset(pe, 0, 0x20);
        if (dpat >= 0 && (uint32_t)dpat < n_pli) memcpy(pe, (void *)(uintptr_t)(plist + 0x20ull * lf_r32(pli + 4ull * (uint64_t)dpat)), 0x20);
        else { P64(pe, 8) = (uint64_t)0x400000 << 40; }
        LF_LINK(d->parent_hash, ipos, next);
        P64(pe, 0) = d->hash | ((uint64_t)next << 40);
        P64(pe, 8) = d->parent_hash | (P64(pe, 8) & ~LF_MASK40);
        P64(pe, 16) = d->name_hash | (P64(pe, 16) & ~LF_MASK40);
        P32(pli2, 4ull * ipos) = ppos;
        P64(pidx2, 8ull * (n_plist + k_path)) = d->hash | ((uint64_t)ipos << 40);
        k_path++;
    }
    int cloned_paths = 0;
    for (int j = 0; j < nn; j++) {
        LooseNew *nw = &g_lf_new[j];
        if (nw->kind == 3) continue;
        const uint8_t *np = paths2 + 0x20ull * (n_path + (uint32_t)j);
        uint64_t dhash = lf_r64(paths + 0x20ull * (uint64_t)nw->donor_pi) & LF_MASK40;
        uint32_t ipos = n_pli + k_path, ppos = n_plist + k_path, next;
        int64_t dpat = lf_bsearch(pidx, n_plist, dhash);
        uint8_t *pe = plist2 + 0x20ull * ppos;
        memset(pe, 0, 0x20);
        if (dpat >= 0 && (uint32_t)dpat < n_pli) { memcpy(pe, (void *)(uintptr_t)(plist + 0x20ull * lf_r32(pli + 4ull * (uint64_t)dpat)), 0x20); cloned_paths++; }
        else { P64(pe, 16) = P64(np, 24) & LF_MASK40; P64(pe, 24) = P64(np, 8) & LF_MASK40; }      /* file name, extension from the file path row */
        if (nw->kind == 5) { P64(pe, 16) = (P64(np, 24) & LF_MASK40) | (P64(pe, 16) & ~LF_MASK40); P64(pe, 24) = (P64(np, 8) & LF_MASK40) | (P64(pe, 24) & ~LF_MASK40); }   /* its own name, extension */
        LF_LINK(nw->parent_hash, ipos, next);
        P64(pe, 0) = nw->hash | ((uint64_t)next << 40);
        P64(pe, 8) = nw->parent_hash | (P64(pe, 8) & ~LF_MASK40);
        P32(pli2, 4ull * ipos) = ppos;
        P64(pidx2, 8ull * (n_plist + k_path)) = nw->hash | ((uint64_t)ipos << 40);
        k_path++;
    }
    qsort(pidx2, (size_t)n_plist + add_p, 8, lf_cmp40);
    qsort(fidx2, (size_t)n_fold + (size_t)new_fold, 8, lf_cmp40);
    // ---- the switch: row arrays first, then the counts, then the lookups that make the new rows reachable
    g_lf_sync[0].old = (uint8_t *)(uintptr_t)ld; g_lf_sync[0].now = ld2; g_lf_sync[0].count = n_ld; g_lf_sync[0].item = 0x18;
    g_lf_sync[1].old = (uint8_t *)(uintptr_t)lfp; g_lf_sync[1].now = lfp2; g_lf_sync[1].count = n_lfp; g_lf_sync[1].item = 8;
    /* N9 (run n9ui, a quiet machine: 0 rows in use when the growth began, 65 at the switch, and the game then stood
     * still for ever right after it): the copies of the two "loaded" arrays were taken at the BEGINNING of the growth,
     * several hundred milliseconds of table building before this point. Rows the game took into use in between were
     * neither in the new arrays at the switch nor pinned (the pin list is made from the new arrays). The old rows of
     * both arrays are therefore copied AGAIN here, immediately before the snapshot, the pin list and the switch: the
     * window shrinks to this copy (about 9 MB) and every row in use at the switch is pinned. The rows of OUR new files
     * stand behind the old ones and are not touched. */
    memcpy(ld2, (void *)(uintptr_t)ld, (size_t)n_ld * 0x18);
    memcpy(lfp2, (void *)(uintptr_t)lfp, (size_t)n_lfp * 8);
    for (int a = 0; a < 2; a++) {
        g_lf_sync[a].snap = VirtualAlloc(NULL, g_lf_sync[a].count * g_lf_sync[a].item + 64, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
        memcpy(g_lf_sync[a].snap, g_lf_sync[a].now, g_lf_sync[a].count * g_lf_sync[a].item);      /* what was copied, not what the old array holds by now */
    }
    /* the rows in use right now (loaded data: byte + 0xc; loaded file path: the "loaded" word): pinned, see the sync thread */
    g_lf_pin_count = 0;
    for (uint32_t i = 0; i < n_ld && g_lf_pin_count < 2048; i++)
        if (ld2[0x18ull * i + 0xc]) { g_lf_pin[g_lf_pin_count].array = 0; g_lf_pin[g_lf_pin_count].index = i; memcpy(g_lf_pin[g_lf_pin_count].snap, ld2 + 0x18ull * i, 0x18); g_lf_pin_count++; }
    for (uint32_t i = 0; i < n_lfp && g_lf_pin_count < 4096; i++)
        if (P32(lfp2, 8ull * i + 4)) { g_lf_pin[g_lf_pin_count].array = 1; g_lf_pin[g_lf_pin_count].index = i; memcpy(g_lf_pin[g_lf_pin_count].snap, lfp2 + 8ull * i, 8); g_lf_pin_count++; }
    g_lf_new_count = nn;
    g_lf_first_new_info = n_info;
    lf_w64(arc + 0x60, (uint64_t)(uintptr_t)paths2); lf_w64(arc + 0x68, (uint64_t)(uintptr_t)ind2); lf_w64(arc + 0x90, (uint64_t)(uintptr_t)infos2);
    lf_w64(arc + 0x78, (uint64_t)(uintptr_t)dirs2);
    if (n_tmpl) { lf_w64(arc + 0x98, (uint64_t)(uintptr_t)to_data2); lf_w64(arc + 0xa0, (uint64_t)(uintptr_t)datas2); }
    if (g_lf_fo_count) lf_w64(arc + 0x80, (uint64_t)(uintptr_t)fo2);
    if (g_lf_child_count) lf_w64(arc + 0x88, (uint64_t)(uintptr_t)childh2);
    lf_w64(fsinfo + 8, (uint64_t)(uintptr_t)lfp2); lf_w64(fsinfo + 0x10, (uint64_t)(uintptr_t)ld2);
    lf_w32(hdr + 4, n_path + (uint32_t)nn); lf_w32(hdr + 8, n_ind + (uint32_t)nn);
    /* the header's file info count (+0x18) is NOT raised: the new infos stand behind all three parts of the array (the
     * count is the first part's length, and the other parts are addressed behind it) */
    lf_w32(fsinfo + 0x18, n_lfp + (uint32_t)nn); lf_w32(fsinfo + 0x1c, n_ld + (uint32_t)nn);
    const char *part = getenv("SSBU_LOOSE_STAGE2");            /* diagnosis: "files" = the file tables only, "search" = the search tables only */
    int do_files = !(part && part[0] == 's'), do_search = !(part && part[0] == 'f');
    if (do_files) {
        lf_w64(arc + 0x58, (uint64_t)(uintptr_t)ent2); lf_w64(arc + 0x50, (uint64_t)(uintptr_t)buck2);
        if (n_group && !(diag & 1)) { lf_w64(arc + 0x70, (uint64_t)(uintptr_t)dirx2); lf_w32(hdr + 0xc, n_dir + (uint32_t)n_group); }
    }
    if (do_search) {
        lf_w64(search + 0x18, (uint64_t)(uintptr_t)flist2); lf_w64(search + 0x30, (uint64_t)(uintptr_t)plist2); lf_w64(search + 0x28, (uint64_t)(uintptr_t)pli2);
        lf_w64(search + 0x10, (uint64_t)(uintptr_t)fidx2); lf_w64(search + 0x20, (uint64_t)(uintptr_t)pidx2);
        lf_w32(body, n_fold + (uint32_t)new_fold); lf_w32(body + 4, n_pli + add_p); lf_w32(body + 8, n_plist + add_p);
    }
    g_lf_search_on = do_search && do_files;
    {   /* does any of the game's objects hold a second pointer into an old array? */
        uint64_t olds[6] = { paths, ind, infos, lfp, ld, dirs }, sizes[6] = { 0x20ull * n_path, 8ull * n_ind, 16ull * n_info, 8ull * n_lfp, 0x18ull * n_ld, 0x34ull * n_dir };
        const char *names[6] = { "file paths", "file info indices", "file infos", "loaded file paths", "loaded datas", "directories" };
        uint64_t objs[3] = { lf_r64(0x7105331f28ull), fsinfo, arc }; const char *onames[3] = { "resource service", "filesystem info", "archive tables" };
        size_t lens[3] = { 0x2000, 0x100, 0x130 };
        int hits = 0;
        for (int o = 0; o < 3; o++)
            for (size_t off = 0; off + 8 <= lens[o] && lf_readable(objs[o] + off, 8); off += 8) {
                uint64_t v = lf_r64(objs[o] + off);
                for (int a = 0; a < 6; a++) if (v >= olds[a] && v < olds[a] + sizes[a]) { hits++; lf_logf("[loose] stage 2: %s + 0x%zx still points into the OLD %s (+0x%llx)", onames[o], off, names[a], (unsigned long long)(v - olds[a])); }
            }
        lf_logf("[loose] stage 2: %d pointers into old arrays left in the resource service (0x2000 bytes), the filesystem info and the archive tables", hits);
    }
    g_lf_grown = 1;
    { HANDLE th = CreateThread(NULL, 0, lf_sync_thread, NULL, 0, NULL); if (th) CloseHandle(th); }
    lf_logf("[loose] stage 2: rows in use at the switch: %u loaded file paths, %u loaded datas (at the start of the growth: %u, %u)", lf_r32(fsinfo + 0x20), lf_r32(fsinfo + 0x24), use0, use1);
    lf_logf("[loose] stage 2: tables GROWN for %d new file paths in %d group(s) + %d without a group (%d without a donor file not added): file paths %u -> %u, file info indices %u -> %u, "
            "file infos %u -> %u, hash entries %u -> %u (%u buckets rebuilt), directories %u -> %u, loaded file paths -> %u, loaded datas -> %u; search: folders %u -> %u (%d new, %d from the "
            "donor's row), paths and path indices %u -> %u (%d file entries from the donor's row); data rows shared with the donors; %d decompressed sizes raised, %d regional files",
            nn, n_group, standalone, no_donor, n_path, n_path + nn, n_ind, n_ind + nn, n_info, n_info + n_newinfo, n_ent, lf_r32((uint64_t)(uintptr_t)buck2), nb, n_dir, n_dir + n_group,
            n_lfp + nn, n_ld + nn, n_fold, n_fold + new_fold, new_fold, cloned_folders, n_plist, n_plist + add_p, cloned_paths, raised, regional);
    for (int o = 0; o < g_lf_owner_count; o++)
        lf_logf("[loose] stage 2: fighter %s (donor %s): %d files in its folder, %d of them under paths the archive does not have: rows added; in its group(s): %d more own files renamed "
                "(the donor's bytes under the fighter's name: the donor fallback), %d under private hashes, %d shared rows", g_lf_owner[o].name,
                g_lf_owner[o].donor, g_lf_owner[o].files, g_lf_owner[o].new_files, g_lf_owner[o].renamed, g_lf_owner[o].private_rows, g_lf_owner[o].shared_rows);
    // self-check through the game's own lookups' data: every new path and every group must be found
    int bad = 0, checked = 0, gbad = 0;
    for (int j = 0; j < nn; j++) {
        if (g_lf_new[j].kind == 3) continue;
        checked++;
        if (lf_find(arc, g_lf_new[j].hash) != (int64_t)(n_path + (uint32_t)j) || lf_bsearch((uint64_t)(uintptr_t)pidx2, n_plist + add_p, g_lf_new[j].hash) < 0) bad++;
    }
    for (int g = 0; g < n_group; g++) if (lf_bsearch((uint64_t)(uintptr_t)dirx2, n_dir + (uint32_t)n_group, g_lf_group[g].hash) != (int64_t)g_lf_group[g].dir_index) gbad++;
    lf_logf("[loose] stage 2: self-check: %d of %d new paths found through the hash buckets and the search path index; %d of %d groups found through the directory index; %d new search folders",
            checked - bad, checked, n_group - gbad, n_group, new_fold);
#undef P64
#undef P32
#undef LF_LINK
}

// once: find every loose file in the archive's tables and make room for it
static void lf_resolve(uint64_t fsinfo, uint64_t arc) {
    uint64_t header = lf_r64(arc + 0x40), paths = lf_r64(arc + 0x60), indices = lf_r64(arc + 0x68);
    uint64_t infos = lf_r64(arc + 0x90), to_data = lf_r64(arc + 0x98), datas = lf_r64(arc + 0xa0);
    uint32_t n = lf_r32(header + 4);
    int found = 0, pending = 0;
    for (int k = 0; k < g_lf_count; k++) {
        LooseFile *f = &g_lf[k];
        int64_t i = lf_find(arc, f->hash);
        if (i < 0) continue;
        uint64_t q = lf_r64(paths + 0x20ull * (uint64_t)i);
        f->path_index = (int32_t)i;
        f->indice_index = (uint32_t)(q >> 40);
        f->info_index = lf_r32(indices + 8ull * f->indice_index + 4) & 0xffffffu;
        uint32_t itd = lf_r32(infos + 16ull * f->info_index + 8);
        f->data_index = lf_r32(to_data + 12ull * itd + 4);
        uint64_t d = datas + 16ull * f->data_index;
        f->arc_size = lf_r32(d + 8);
        if (f->size > f->arc_size) lf_w32(d + 8, f->size);
        found++;
        lf_logf("[loose] %s: file path index 0x%x, file info 0x%x, data 0x%x: archive size %u (compressed %u), loose size %u%s",
                f->arc_path, (unsigned)i, f->info_index, f->data_index, f->arc_size, lf_r32(d + 4), f->size, f->size > f->arc_size ? " (size in the table raised)" : "");
    }
    for (int k = 0; k < g_lf_count; k++) {
        if (g_lf[k].path_index >= 0) continue;
        if (g_lf[k].owner >= 0) pending++;
        else lf_logf("[loose] %s (%u bytes): not in the archive, and its folder has no manifest: NOT served", g_lf[k].arc_path, g_lf[k].size);
    }
    lf_logf("[loose] %d loose files, %d found among the archive's %u file paths, %d under new paths of fighter folders", g_lf_count, found, n, pending);
    if (pending) {
        const char *e = getenv("SSBU_LOOSE_STAGE2");
        /* N7 hand-back: stage 2 is OPT-IN (SSBU_LOOSE_STAGE2=1, or "files" / "search" for diagnosis) until a match is
         * reached with own groups (plan\phases\N7_own_files2.md 2.5); without it a fighter folder behaves as in N5 */
        /* N8: a match is reached and a clone on its own files equals its donor (runs n8a1 / n8am): stage 2 is the
         * DEFAULT again for fighter folders (the layer itself only runs with SSBU_CHARACTERS / SSBU_LOOSE_FILES);
         * SSBU_LOOSE_STAGE2=0 switches it off */
        if (e && e[0] == '0') lf_logf("[loose] stage 2 is off (SSBU_LOOSE_STAGE2=0): new paths stay with the donor fallback");
        else lf_grow(fsinfo, arc);
    }
}
// N9 (diagnosis, SSBU_LOOSE_TRACE=1): who loads the files that are asked singly (the sound banks)? A thread of ours
// watches the "loaded" rows of every new file under "sound/" AND of its donor file and logs each change (path row:
// data index, loaded; data row: buffer, users, in use, state); the decompress / copy hooks log every single-file batch.
static int g_lf_trace; static long g_lf_trace_n;
static DWORD WINAPI lf_watch_thread(LPVOID arg) {
    (void)arg;
    static uint8_t last[64][2][0x20]; int ids[64], n = 0; long lines = 0;
    for (int k = 0; k < g_lf_count && n < 64; k++) if (g_lf[k].is_new && g_lf[k].path_index >= 0 && (g_lf[k].is_new == 2 || !strncmp(g_lf[k].arc_path, "sound/", 6) || !strncmp(g_lf[k].arc_path, "ui/", 3))) ids[n++] = k;
    lf_logf("[loose] trace: watching the loaded rows of %d new sound files and of their donor files", n);
    for (int round = 0; round < 60000 && lines < 400; round++) {
        uint64_t fsinfo, arc;
        if (lf_tables(0, &fsinfo, &arc)) {
            uint64_t lp = lf_r64(fsinfo + 8), ld = lf_r64(fsinfo + 0x10), paths = lf_r64(arc + 0x60);
            for (int i = 0; i < n; i++) {
                LooseFile *f = &g_lf[ids[i]];
                for (int side = 0; side < 2; side++) {
                    int64_t pi = side ? lf_find(arc, f->donor_hash) : f->path_index;
                    if (pi < 0) continue;
                    uint32_t xi = side ? (uint32_t)(lf_r64(paths + 0x20ull * (uint64_t)pi) >> 40) : f->indice_index;
                    uint8_t now[0x20];
                    if (!lf_readable(lp + 8ull * (uint64_t)pi, 8) || !lf_readable(ld + 0x18ull * xi, 0x18)) continue;
                    memcpy(now, (void *)(uintptr_t)(lp + 8ull * (uint64_t)pi), 8); memcpy(now + 8, (void *)(uintptr_t)(ld + 0x18ull * xi), 0x18);
                    if (!memcmp(now, last[i][side], 0x20)) continue;
                    memcpy(last[i][side], now, 0x20); lines++;
                    uint64_t buf; uint32_t users, w0, w1; memcpy(&buf, now + 8, 8); memcpy(&users, now + 16, 4); memcpy(&w0, now, 4); memcpy(&w1, now + 4, 4);
                    uint32_t head = lf_readable(buf, 8) ? lf_r32(buf) : 0, head2 = lf_readable(buf, 8) ? lf_r32(buf + 4) : 0;
                    lf_logf("[loose] trace: %s %s: path row %x {data index %x, loaded %x}; data row %x {buffer %llx, users %u, in use %u, state %u}; first words of the buffer %08x %08x", side ? "DONOR of" : "OWN",
                            f->arc_path, (unsigned)pi, w0, w1, xi, (unsigned long long)buf, users, now[20], now[21], head, head2);
                }
            }
        }
        Sleep(20);
    }
    return 0;
}
static int lf_ready(uint64_t service) {
    if (g_lf_resolved) return 1;
    uint64_t fsinfo, arc;
    if (!lf_tables(service, &fsinfo, &arc)) return 0;
    EnterCriticalSection(&g_lf_lock);
    if (!g_lf_resolved) {
        lf_resolve(fsinfo, arc); g_lf_resolved = 1;
        const char *te = getenv("SSBU_LOOSE_TRACE");
        if (te && te[0] == '1') { g_lf_trace = 1; CloseHandle(CreateThread(NULL, 0, lf_watch_thread, NULL, 0, NULL)); }
    }
    LeaveCriticalSection(&g_lf_lock);
    return 1;
}
static void lf_trace_batch(const char *what, uint64_t service, uint64_t arc, uint32_t info_index, uint64_t type) {
    if (!g_lf_trace || lf_r32(service + 0x22c) != 1 || g_lf_trace_n >= 300) return;
    uint64_t infos = lf_r64(arc + 0x90), paths = lf_r64(arc + 0x60);
    uint32_t pi = lf_r32(infos + 16ull * info_index) & 0xffffffu;
    g_lf_trace_n++;
    lf_logf("[loose] trace: %s of a SINGLE-file batch: file info 0x%x (ours start at 0x%x), its path row %x hash %llx, x21 %llx", what, info_index, g_lf_first_new_info, pi,
            (unsigned long long)(lf_r64(paths + 0x20ull * pi) & LF_MASK40), (unsigned long long)type);
}
// N7: THE GROWTH AS EARLY AS POSSIBLE. Polled by the host from process start (every millisecond): as soon as the game
// has published its tables (archive tables, loaded tables with the archive's counts, search tables) and they stayed
// the same for three polls, the tables are resolved and grown - before the first file request when the poll wins,
// so that no object of the game can hold a pointer into an old "loaded" array (a stale pointer of that kind is what
// [inference] kept run n7a2, and N6's b3 / b4, from ever leaving the opening: the waiter reads the old row, the
// loader writes the new one). The first decompress stays the fallback trigger. The log says which one it was and how
// many rows were in use.
static int loose_files_early(void) {
    static uint64_t seen_arc, seen_search; static int stable;
    uint64_t fsinfo, arc;
    if (g_lf_resolved || !g_lf_scanned) return g_lf_resolved;
    if (!lf_tables(0, &fsinfo, &arc) || !lf_readable(fsinfo, 0x80)) return 0;
    uint64_t holder = lf_r64(fsinfo + 0x78);
    if (!lf_readable(holder, 16)) return 0;
    uint64_t search = lf_r64(holder + 8), hdr = lf_r64(arc + 0x40);
    if (!lf_readable(search, 0x38) || !lf_readable(hdr, 0x48)) return 0;
    uint64_t body = lf_r64(search + 8);
    if (!lf_readable(body, 12)) return 0;
    uint32_t n_path = lf_r32(hdr + 4), n_ind = lf_r32(hdr + 8);
    if (n_path < 1000 || lf_r32(fsinfo + 0x18) != n_path || lf_r32(fsinfo + 0x1c) != n_ind || !lf_r32(body) || lf_r32(body + 4) != lf_r32(body + 8)) return 0;
    for (int off = 0x50; off <= 0xa0; off += 8) if (off != 0x48 && !lf_r64(arc + (uint64_t)off)) return 0;
    for (int off = 0x10; off <= 0x30; off += 8) if (!lf_r64(search + (uint64_t)off)) return 0;
    if (!lf_r64(fsinfo + 8) || !lf_r64(fsinfo + 0x10) || !lf_r64(fsinfo + 0x40)) return 0;
    if (!lf_readable(lf_r64(search + 0x20) + 8ull * lf_r32(body + 8) - 8, 8) || !lf_readable(lf_r64(fsinfo + 0x10) + 0x18ull * n_ind - 0x18, 0x18)) return 0;
    if (arc != seen_arc || search != seen_search) { seen_arc = arc; seen_search = search; stable = 0; return 0; }
    if (++stable < 3) return 0;
    g_lf_early = 1;
    return lf_ready(0);
}
// for the registry's path fallback: does stage 2 have a row for this path hash? 1 = a file, 2 = a folder, 3 = a load group
static int loose_files_has(uint64_t hash) {
    if (!g_lf_scanned) return 0;
    if (!g_lf_resolved) lf_ready(0);
    if (!g_lf_grown || !g_lf_search_on) return 0;
    for (int g = 0; g < g_lf_group_count; g++) if (g_lf_group[g].hash == hash) return 3;
    for (int j = 0; j < g_lf_new_count; j++) if (g_lf_new[j].kind != 3 && g_lf_new[j].hash == hash) return 1;
    for (int i = 0; i < g_lf_folder_count; i++) if (!g_lf_folder[i].exists && g_lf_folder[i].hash == hash) return 2;
    return 0;
}
static void lf_serve(uint64_t fsinfo, uint32_t info_index, int raw);
// 0x71039a4040: one step of the decompression of the file the inflate thread is working on
static void lf_inflate(Ctx *c, void *user) {
    (void)user;
    uint64_t lr = c->x[30], service = c->x[19], index = c->x[27];
    int from_thread = lr >= 0x71035444c0ull && lr < 0x71035456d8ull;
    if (from_thread && !g_lf_resolved) lf_ready(service);
    g_lf_orig_inflate(c);
    if (!from_thread || c->x[0] != 0) return;
    uint64_t fsinfo, arc;
    if (!lf_tables(service, &fsinfo, &arc)) return;
    uint32_t info_index = lf_r32(service + 0x230) + (uint32_t)index;
    lf_trace_batch("decompress finished", service, arc, info_index, c->x[21]);
    if (g_lf_grown && g_lf_first_new_info && info_index >= g_lf_first_new_info && info_index < g_lf_first_new_info + (uint32_t)g_lf_plan_count) {
        /* a file of one of OUR file infos was decompressed: which kind of row */
        int j = g_lf_plan[info_index - g_lf_first_new_info].new_index;
        int kind = j < 0 ? 0 : g_lf_new[j].kind;
        g_lf_done_kind[kind]++;
        if (kind == 2 && j >= 0) g_lf_owner[g_lf_new[j].owner].donor_bytes_files++;
        for (int g = 0; g < g_lf_group_count; g++) {
            LooseGroup *gr = &g_lf_group[g];
            if (info_index < gr->info_start || info_index >= gr->info_start + gr->count) continue;
            gr->finished++;
            if (gr->finished == 1 || (uint32_t)index + 1 == lf_r32(service + 0x22c))
                lf_logf("[loose] stage 2: GROUP %s: the game's load thread works on its range (batch start 0x%x, file %u of %u; decompressed so far in this group %ld; all groups: %ld brought by "
                        "folders, %ld renamed with the donor's bytes, %ld private, %ld shared rows)", gr->path, lf_r32(service + 0x230), (unsigned)index + 1, lf_r32(service + 0x22c), gr->finished,
                        g_lf_done_kind[1], g_lf_done_kind[2], g_lf_done_kind[3], g_lf_done_kind[0]);
        }
    }
    lf_serve(fsinfo, info_index, 0);
}
// the folder's file for the file info `info_index`, written over the content of the game's buffer of that file.
// raw = 0: called when the decompress of the file has finished; raw = 1 (N8): called after each raw copy of a file
// the archive stores UNCOMPRESSED (such a file never passes the decompress call; the last copy's rewrite stays)
static long g_lf_served_raw, g_lf_footer;
static void lf_serve(uint64_t fsinfo, uint32_t info_index, int raw) {
    for (int k = 0; k < g_lf_count; k++) {
        LooseFile *f = &g_lf[k];
        if (f->path_index < 0 || f->info_index != info_index) continue;
        if (raw == 1 && ++g_lf_served_raw <= 3)
            lf_logf("[loose] %s: stored UNCOMPRESSED in the archive: served at the load thread's raw copy (file info 0x%x)", f->arc_path, info_index);
        uint64_t datas = lf_r64(fsinfo + 0x10);
        uint64_t buf = lf_r64(datas + 0x18ull * f->indice_index);
        if (!lf_readable(buf, f->size)) { lf_logf("[loose] %s: the game's buffer %llx is not there or too small: NOT served", f->arc_path, (unsigned long long)buf); return; }
        FILE *fp = fopen(f->disk_path, "rb");
        if (!fp) { lf_logf("[loose] %s: cannot open %s", f->arc_path, f->disk_path); return; }
        size_t got = fread((void *)(uintptr_t)buf, 1, f->size, fp);
        fclose(fp);
        f->served++;
        {   /* N10: (1) a texture file ends with a fixed footer that its reader takes from the END of the buffer: when the
             * folder's texture is SMALLER than the buffer (the size in the file-data row: the donor file's), the footer
             * is copied to the buffer's end too (what reference\ARCropolis does in handle_file_replace: 0xb0 bytes).
             * (2) read-back for a virtual record: what the game's buffer holds after the write. */
            uint64_t tb, ta;
            const char *e4 = strrchr(f->arc_path, '.');
            if (lf_tables(0, &tb, &ta)) {
                uint32_t cap = lf_r32(lf_r64(ta + 0xa0) + 16ull * f->data_index + 8);
                if (e4 && !strcmp(e4, ".nutexb") && got >= 0xb0 && cap > got && cap < 0x10000000u && lf_readable(buf, cap)) {
                    memcpy((void *)(uintptr_t)(buf + cap - 0xb0), (void *)(uintptr_t)(buf + got - 0xb0), 0xb0);
                    if (++g_lf_footer <= 4 || getenv("SSBU_LOOSE_VERBOSE"))
                        lf_logf("[loose] %s: %u bytes in a buffer of %u (the donor file's size): the texture footer (0xb0 bytes) copied to the buffer's end as well", f->arc_path, (unsigned)got, cap);
                }
                if (raw == 2 && f->served == 1) {
                    uint32_t crc = 0xffffffffu; const uint8_t *bp = (const uint8_t *)(uintptr_t)buf;
                    for (size_t q = 0; q < got; q++) { crc ^= bp[q]; for (int k2 = 0; k2 < 8; k2++) crc = (crc >> 1) ^ (0xedb88320u & (0u - (crc & 1))); }
                    lf_logf("[loose] VIRTUAL record served: %s: %u bytes written into the game's buffer %llx (size in its own file-data row %u, file info 0x%x); read back from the buffer: crc32 %08x, "
                            "first words %08x %08x", f->arc_path, (unsigned)got, (unsigned long long)buf, cap, info_index, ~crc, got >= 8 ? lf_r32(buf) : 0, got >= 8 ? lf_r32(buf + 4) : 0);
                }
            }
        }
        if (f->is_new) {
            g_lf_served_new++; g_lf_served_new_bytes += got;
            if (f->owner >= 0 && f->served == 1) { g_lf_owner[f->owner].served++; g_lf_owner[f->owner].bytes += got; }
        }
        if (!f->is_new || (f->served == 1 && (g_lf_served_new <= 3 || getenv("SSBU_LOOSE_VERBOSE"))))
            lf_logf("[loose] served %s%s: %u bytes from %s (archive copy: %u bytes; file info 0x%x; time number %ld)", f->is_new ? "NEW PATH " : "", f->arc_path, (unsigned)got,
                    f->disk_path, f->arc_size, info_index, f->served);
        if (f->is_new && f->owner >= 0 && f->served == 1 && (g_lf_owner[f->owner].served % 100 == 0 || g_lf_owner[f->owner].served == g_lf_owner[f->owner].new_files))
            lf_logf("[loose] stage 2: fighter %s: %ld of its %d files SERVED from its own folder under its own name, %llu bytes (%ld raw-copy rewrites of uncompressed files so far, all "
                    "fighters); %ld more files of its group filled with the donor's bytes (the folder does not bring them)", g_lf_owner[f->owner].name, g_lf_owner[f->owner].served,
                    g_lf_owner[f->owner].new_files, g_lf_owner[f->owner].bytes, g_lf_served_raw, g_lf_owner[f->owner].donor_bytes_files);
        return;
    }
}
// N8: the host's copy function 0x71039bfb30 as the load thread 0x71035444c0 calls it for a file stored uncompressed
// (two call sites, return addresses 0x7103544d88 and 0x7103544e18: destination = the file's buffer, [x26]); x19 = the
// resource service and x27 = the index in the batch, as at the decompress call. Any other caller: untouched.
static HookOrig g_lf_orig_copy;
static void lf_rawcopy(Ctx *c, void *user) {
    (void)user;
    uint64_t lr = c->x[30], service = c->x[19], index = c->x[27];
    /* N10: a VIRTUAL record (SSBU_LOOSE_TEMPLATE=3) arrives at the one-call site with x2 = the folder file's size and
     * x1 = the running pointer into the read window, where no bytes of this file are: the copy itself is NOT run (it
     * would read the file's size from the window, possibly past its end); the folder's file is written instead. */
    if (lr == 0x7103545198ull && g_lf_virtual && g_lf_grown && g_lf_resolved) {
        uint64_t fsinfo, arc;
        uint32_t ii = lf_tables(service, &fsinfo, &arc) ? lf_r32(service + 0x230) + (uint32_t)index : 0;
        if (ii >= g_lf_first_new_info && ii < g_lf_first_new_info + (uint32_t)g_lf_plan_count) {
            int j = g_lf_plan[ii - g_lf_first_new_info].new_index;
            if (j >= 0 && g_lf_new[j].kind == 5) { lf_serve(fsinfo, ii, 2); return; }
        }
    }
    g_lf_orig_copy(c);
    /* 0x7103545198: THE USUAL CASE, found by reading after run n8b1 had shown 0 calls from the other two: a file that
     * lies completely inside the current read window is copied by ONE call at 0x7103545194 and goes straight to the
     * common end 0x7103545438; the other two sites are the pieces of a file that spans windows. In ssbu_n8g.exe; NOT RUN. */
    if (lr != 0x7103544d88ull && lr != 0x7103544e18ull && lr != 0x7103545198ull) return;
    uint64_t fsinfo, arc;
    if (!g_lf_resolved || !lf_tables(service, &fsinfo, &arc)) return;
    lf_trace_batch("raw copy", service, arc, lf_r32(service + 0x230) + (uint32_t)index, lr);
    lf_serve(fsinfo, lf_r32(service + 0x230) + (uint32_t)index, 1);
}

// two steps for a caller that may have to wait for the hook table (the exe): scan once, then install until it works
static int loose_files_scan(void (*log)(const char *)) {
    g_lf_log = log;
    char root[MAX_PATH * 2];
    const char *e = getenv("SSBU_CHARACTERS");
    if (e && e[0]) snprintf(root, sizeof root, "%s", e);
    else {
        DWORD n = GetModuleFileNameA(NULL, root, MAX_PATH);
        while (n && root[n - 1] != '\\' && root[n - 1] != '/') n--;
        snprintf(root + n, sizeof root - n, "..\\characters");
    }
    if (GetFileAttributesA(root) == INVALID_FILE_ATTRIBUTES) { lf_logf("[loose] no folder %s: nothing installed", root); return 0; }
    char pat[MAX_PATH * 2]; WIN32_FIND_DATAA fd;
    snprintf(pat, sizeof pat, "%s\\*", root);
    HANDLE h = FindFirstFileA(pat, &fd);
    if (h != INVALID_HANDLE_VALUE) {
        do {
            if (fd.cFileName[0] == '.' || !(fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY)) continue;
            char sub[MAX_PATH * 2], mf[MAX_PATH * 2], js[4096]; snprintf(sub, sizeof sub, "%s\\%s", root, fd.cFileName);
            int before = g_lf_count, owner = -1;
            snprintf(mf, sizeof mf, "%s\\fighter.json", sub);
            FILE *fp = fopen(mf, "rb");
            if (fp) {
                size_t n = fread(js, 1, sizeof js - 1, fp); fclose(fp); js[n] = 0;
                if (g_lf_owner_count < LF_MAX_OWNERS) {
                    LooseOwner *o = &g_lf_owner[g_lf_owner_count];
                    memset(o, 0, sizeof *o);
                    if (!lf_json_str(js, "name", o->name, sizeof o->name)) snprintf(o->name, sizeof o->name, "%.31s", fd.cFileName);
                    if (lf_json_str(js, "donor", o->donor, sizeof o->donor)) owner = g_lf_owner_count++;
                }
            }
            lf_scan(sub, "", owner);
            if (owner >= 0) lf_clone_list(sub, owner, before);
            lf_logf("[loose] folder %s: %d files%s", sub, g_lf_count - before, owner >= 0 ? " (a fighter's folder: its manifest names the donor)" : "");
        } while (FindNextFileA(h, &fd));
        FindClose(h);
    }
    if (!g_lf_count) { lf_logf("[loose] %s holds no files: nothing installed", root); return 0; }
    InitializeCriticalSection(&g_lf_lock);
    g_lf_scanned = 1;
    lf_logf("[loose] loose-file layer: %d files under %s", g_lf_count, root);
    return g_lf_count;
}
static int loose_files_install(int (*install)(uint64_t, HookFn, void *, HookOrig *), int quiet) {
    int ok = install(0x71039a4040ull, lf_inflate, NULL, &g_lf_orig_inflate);
    if (ok || !quiet) lf_logf("[loose] hook on the per-file decompress 0x71039a4040: %s", ok ? "installed" : "FAILED");
    if (ok) {       /* N8: files stored uncompressed. OPT-IN (SSBU_LOOSE_RAW=1): run n8b1 showed 0 calls from the two
                     * call sites for the 32 folder files that are never served, so these sites are NOT the path such a
                     * file takes; the hook stays for the next session's trace and is off by default (it sits on the
                     * host's copy function, which every guest copy passes) */
        const char *re = getenv("SSBU_LOOSE_RAW"), *t3 = getenv("SSBU_LOOSE_TEMPLATE");
        /* N10: virtual records (SSBU_LOOSE_TEMPLATE=3) are filled at this hook: it comes with that switch */
        if ((re && re[0] == '1') || ((!t3 || !t3[0] || t3[0] == '3') && g_lf_owner_count > 0 && !(re && re[0] == '0'))) {
            int ok2 = install(0x71039bfb30ull, lf_rawcopy, NULL, &g_lf_orig_copy);
            lf_logf("[loose] hook on the copy function 0x71039bfb30 (the load thread's raw copy of uncompressed files): %s", ok2 ? "installed" : "FAILED (uncompressed files keep the archive's bytes)");
        }
    }
    return ok;
}
static int loose_files_start(int (*install)(uint64_t, HookFn, void *, HookOrig *), void (*log)(const char *)) {
    if (!loose_files_scan(log)) return 0;
    return loose_files_install(install, 0);
}
