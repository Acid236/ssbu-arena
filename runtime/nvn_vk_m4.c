/* Track V, session 4 (M4, design section 5): stages, pipelines and the worker threads that make them AHEAD of the draw.
 * Included by nvn_vk_draw.c (not a build unit of its own); replaces that file's "stages" and "pipelines" sections and its
 * start-up workers of session 3.
 *
 *   - nvnProgramSetShaders (guest thread) -> nvn_vk_program_set: a copy of the program's machine code goes to the worker
 *     queue at once. A worker translates each stage (mx_translate -> glslang -> module, or the record on disk), then makes
 *     pipelines for the pair: the keys of ..\cache\vk\pipes.bin were all made at start; for a pair with no recorded key the
 *     keys are PREDICTED = the pair x the pass signatures most used so far (at most 3), triangles.
 *   - a draw looks up; when its stage or pipeline is being made by a worker it WAITS for it, when nobody makes it it makes
 *     it itself. Either way the render thread stands still at that draw: the present is late, no draw is dropped or
 *     reordered. Every such hold is counted (g_hold_*; "holds so far" in the nvn_vk_perf line).
 *   - with VK_EXT_extended_dynamic_state3 blend enable / equation / write mask, polygon mode, alpha to coverage, depth
 *     clamp and the sample mask are dynamic state, so the key is (stages, topology class, pass formats, samples, logic op,
 *     sample shading): few keys per pair, which is what makes the prediction possible.
 * One lock (g_sh_lock) guards the stage table, the pipeline table, the signature / pair tables and the job queue. */
typedef struct { uint8_t unit, dim, shadow; uint16_t binding; } VSmp;
typedef struct VStage {
    uint64_t h, hb;                                /* h: this variant (code, constants, canonical key, forced outputs); hb: code and constants only */
    int stage, code_len, ok; volatile LONG state, cp_state;      /* state: 1 being made, 2 made (ok says how it went); cp_state: compute pipeline 0 none, 1 being made, 2 made */
    uint32_t key[4], fo, in_attr, out_attr, id, cbufs, ssbos, ssbo_w, images, dep, tex_units; int uses_alpha, nsmp, cp_recorded;
    VkPipeline cp; VkPipelineLayout cl; VkDescriptorSetLayout cdl[2];      /* compute stage: its pipeline */
    uint32_t local[3];
    VSmp smp[64];
    VkShaderModule mod; struct VStage *next, *next_h;
} VStage;
#define MX_VK_VERSION 5u                         /* part of every hash: change it when mx_translate's Vulkan text or these records change */
typedef struct { uint32_t magic; int32_t stage, code_len; uint32_t key[4], fo; uint64_t spv, hb; uint32_t cbufs, ssbos, ssbo_w, images, dep, tex_units, in_attr, out_attr; int32_t uses_alpha, nsmp; VSmp smp[64]; } StageRec;
typedef struct { uint32_t magic, key[4], fo, dep, tex; uint64_t vh; } VarRec;      /* ..\cache\vk\stage\<stage>_<hb>.var: the variants of one code */
#define STAGEREC_MAGIC (0x52545356u + MX_VK_VERSION)
typedef struct { int stage, code_len, serial; const uint8_t *code, *cdata; uint32_t cdata_size, local[3], smem, lmem; } SSrc;
static CRITICAL_SECTION g_sh_lock;
static CONDITION_VARIABLE g_sh_cv, g_jq_cv;        /* g_sh_cv: something was finished; g_jq_cv: a job was queued */
static VkPipelineCache g_pcache;
static LONG64 g_pw_stages, g_pw_pipes, g_pw_failed, g_pipe_miss;
static VStage *g_vstage[4096], *g_vh[4096];        /* by hb, by h */
static uint32_t g_vstage_ids;
static int (*g_glsl_to_spirv)(int, const char *, uint32_t **, size_t *, char *, size_t);
static void (*g_spirv_free)(uint32_t *);
enum { H_STAGE_DRAW, H_STAGE_WAIT, H_PIPE_DRAW, H_PIPE_WAIT, H_N };
static LONG64 g_hold_n[H_N], g_hold_tk[H_N], g_hold_max;
static LONG64 g_w_progs, g_w_stages, g_w_pipes, g_pred_made, g_pred_used, g_set_held, g_set_held_tk;
static void hold_note(int what, LONG64 ticks) { g_hold_n[what]++; g_hold_tk[what] += ticks; if (ticks > g_hold_max) g_hold_max = ticks; }
static uint64_t fnv(uint64_t h, const void *p, size_t n) { const uint8_t *b = p; for (size_t i = 0; i < n; i++) h = (h ^ b[i]) * 0x100000001B3ULL; return h; }
static void compute_pipe_make(VStage *v);
static uint64_t g_spv_unused;
static int g_offline;                              /* --prepare-shaders: stages are translated and written to ..\cache\vk, no Vulkan device exists */
static PFN_vkCmdSetColorBlendEnableEXT vkCmdSetColorBlendEnableEXT;
static PFN_vkCmdSetColorBlendEquationEXT vkCmdSetColorBlendEquationEXT;
static PFN_vkCmdSetColorWriteMaskEXT vkCmdSetColorWriteMaskEXT;
static PFN_vkCmdSetPolygonModeEXT vkCmdSetPolygonModeEXT;
static PFN_vkCmdSetAlphaToCoverageEnableEXT vkCmdSetAlphaToCoverageEnableEXT;
static PFN_vkCmdSetDepthClampEnableEXT vkCmdSetDepthClampEnableEXT;
static PFN_vkCmdSetSampleMaskEXT vkCmdSetSampleMaskEXT;

/* ---------------------------------------------------------------- stages: machine code -> Vulkan GLSL -> SPIR-V -> module */
static int ssrc_of(SSrc *o, const Prog *p, int s) {
    const Stage *st = &p->st[s];
    memset(o, 0, sizeof *o);
    if (!st->code || st->code_len <= 0) return 0;
    o->stage = s; o->code = st->code; o->code_len = st->code_len; o->serial = p->serial;
    if (st->ctl[3] && st->ctl[4]) { o->cdata = st->code - (s == 5 ? 0 : 0x30) + st->ctl[4]; o->cdata_size = st->ctl[3]; }      /* a compute stage has no program header */
    memcpy(o->local, st->local, sizeof o->local); o->smem = st->smem_bytes; o->lmem = st->lmem_bytes;
    return 1;
}
static uint64_t ssrc_hb(const SSrc *o) {
    uint32_t ver = MX_VK_VERSION;
    uint64_t h = fnv(0xcbf29ce484222325ULL ^ (uint64_t)o->stage, o->code, (size_t)o->code_len);
    if (o->stage == 5) { h = fnv(h, o->local, sizeof o->local); h = fnv(h, &o->smem, 4); h = fnv(h, &o->lmem, 4); }
    if (o->cdata) h = fnv(h ^ o->cdata_size, o->cdata, o->cdata_size);
    return fnv(h, &ver, 4);
}
static VkShaderModule module_from_spv(uint64_t h) {              /* any thread; NULL when the file is not there */
    char path[128];
    VkShaderModule mod = NULL;
    snprintf(path, sizeof path, "../cache/vk/spv/%016llx.spv", (unsigned long long)h);
    FILE *fp = fopen(path, "rb");
    if (!fp) return NULL;
    if (g_offline) { fclose(fp); return (VkShaderModule)(uintptr_t)1; }      /* --prepare-shaders: no device; the file being there is all that is asked */
    fseek(fp, 0, SEEK_END); long n = ftell(fp); fseek(fp, 0, SEEK_SET);
    uint32_t *words = n > 20 && n % 4 == 0 ? malloc((size_t)n) : NULL;
    if (words && fread(words, 1, (size_t)n, fp) == (size_t)n && words[0] == 0x07230203) {
        VkShaderModuleCreateInfo ci = {VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO};
        ci.codeSize = (size_t)n; ci.pCode = words;
        if (vkCreateShaderModule(V.device, &ci, NULL, &mod) != VK_SUCCESS) mod = NULL;
    }
    free(words); fclose(fp);
    return mod;
}
static VkShaderModule module_from_glsl(int stage, const char *glsl, const char *what, uint64_t *spv_hash) {      /* any thread */
    char path[128], log[2000];
    uint32_t *words = NULL;
    size_t count = 0;
    VkShaderModule mod = NULL;
    uint64_t h = fnv(0xcbf29ce484222325ULL ^ (uint64_t)stage ^ 0x5601, glsl, strlen(glsl));
    *spv_hash = h;
    if ((mod = module_from_spv(h)) != NULL) { InterlockedIncrement64(&R.modules); return mod; }
    if (!g_glsl_to_spirv(stage, glsl, &words, &count, log, sizeof log)) { printf("nvn_vk: %s: glslang rejected the translated text: %s\n", what, log); fflush(stdout); return NULL; }
    snprintf(path, sizeof path, "../cache/vk/spv/%016llx.spv", (unsigned long long)h);
    FILE *fp = fopen(path, "wb");
    if (fp) { fwrite(words, 4, count, fp); fclose(fp); }
    if (g_offline) { g_spirv_free(words); InterlockedIncrement64(&R.modules); return (VkShaderModule)(uintptr_t)1; }
    VkShaderModuleCreateInfo ci = {VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO};
    ci.codeSize = count * 4; ci.pCode = words;
    VKC(vkCreateShaderModule(V.device, &ci, NULL, &mod));
    g_spirv_free(words);
    InterlockedIncrement64(&R.modules);
    return mod;
}
static int stage_rec_read(int s, uint64_t vh, StageRec *r) {
    char path[128];
    snprintf(path, sizeof path, "../cache/vk/stage/%d_%016llx.st", s, (unsigned long long)vh);
    FILE *fp = fopen(path, "rb");
    if (!fp) return 0;
    size_t got = fread(r, 1, sizeof *r, fp);
    fclose(fp);
    return got == sizeof *r && r->magic == STAGEREC_MAGIC && r->stage == s && r->nsmp >= 0 && r->nsmp <= 64;
}
static void vstage_from_rec(VStage *v, const StageRec *r, uint64_t vh, VkShaderModule mod) {
    v->h = vh; v->hb = r->hb; v->code_len = r->code_len; memcpy(v->key, r->key, 16); v->fo = r->fo;
    v->cbufs = r->cbufs; v->ssbos = r->ssbos; v->ssbo_w = r->ssbo_w; v->images = r->images; v->dep = r->dep; v->tex_units = r->tex_units; v->in_attr = r->in_attr; v->out_attr = r->out_attr;
    v->uses_alpha = r->uses_alpha; v->nsmp = r->nsmp; memcpy(v->smp, r->smp, sizeof v->smp);
    v->mod = mod; v->ok = 1;
}
static int key_fits(int s, const uint32_t *want, const uint32_t *have, uint32_t dep, uint32_t tex) {
    uint32_t da = s == 0 ? dep : 0;
    return !((want[0] ^ have[0]) & da) && !((want[1] ^ have[1]) & da) && !((want[2] ^ have[2]) & tex) && !((want[3] ^ have[3]) & tex);
}
/* g_sh_lock held. The variant of this code that serves `key` (compared under the variant's own masks: a stage that reads no
 * integer attribute and no integer texture has ONE variant whatever the draw's state is). *busy: a variant of the same code
 * still in the making, whose masks are not known yet. */
static VStage *vstage_find(uint64_t hb, int s, int code_len, const uint32_t *key, uint32_t fo, VStage **busy) {
    *busy = NULL;
    for (VStage *v = g_vstage[hb & 4095]; v; v = v->next) {
        if (v->hb != hb || v->stage != s || v->code_len != code_len || v->fo != fo) continue;
        if (v->state < 2) { if (!memcmp(v->key, key, 16)) return v; *busy = v; continue; }
        if (key_fits(s, key, v->key, v->dep, v->tex_units)) return v;
    }
    return NULL;
}
static VStage *vstage_new(uint64_t hb, int s, int code_len, const uint32_t *key, uint32_t fo) {      /* g_sh_lock held */
    VStage *v = calloc(1, sizeof *v);
    v->hb = hb; v->stage = s; v->code_len = code_len; memcpy(v->key, key, 16); v->fo = fo; v->id = ++g_vstage_ids; v->state = 1;
    v->next = g_vstage[hb & 4095]; g_vstage[hb & 4095] = v;
    return v;
}
/* Any thread, no lock: fills v (in the table, state 1) from its record on disk, else with the translator and glslang. */
static void vstage_build(VStage *v, const SSrc *src) {
    int s = v->stage, done = 0;
    char path[128];
    StageRec r;
    snprintf(path, sizeof path, "../cache/vk/stage/%d_%016llx.var", s, (unsigned long long)v->hb);
    FILE *fp = fopen(path, "rb");
    if (fp) {
        VarRec e;
        while (!done && fread(&e, 1, sizeof e, fp) == sizeof e) {
            VkShaderModule mod;
            if (e.magic != STAGEREC_MAGIC || e.fo != v->fo || !key_fits(s, v->key, e.key, e.dep, e.tex)) continue;
            if (stage_rec_read(s, e.vh, &r) && (mod = module_from_spv(r.spv)) != NULL) { vstage_from_rec(v, &r, e.vh, mod); InterlockedIncrement64(&R.modules); done = 1; }
        }
        fclose(fp);
    }
    if (!done) {
        MxIn in;
        MxOut out;
        char what[64];
        memset(&in, 0, sizeof in); memset(&out, 0, sizeof out);
        in.stage = s; in.code = src->code; in.code_len = src->code_len; in.cdata = src->cdata; in.cdata_size = src->cdata ? src->cdata_size : 0;
        in.int_attrs = v->key[0]; in.sint_attrs = v->key[1]; in.int_tex = v->key[2]; in.sint_tex = v->key[3]; in.force_out = v->fo;
        in.target = 1; in.binding_base = 40u * (unsigned)s; in.ssbo_base = 40u * (unsigned)s + 20; in.tex_base = 40u * (unsigned)s; in.image_base = 40u * (unsigned)s + 32; in.wmask_binding = 40u * (unsigned)s + 38;
        if (s == 5) {                              /* compute has a layout of its own (design, section 4): the bindings of stage 0 */
            in.binding_base = 0; in.ssbo_base = 20; in.tex_base = 0; in.image_base = 32; in.wmask_binding = 38; in.track_writes = 1;
            memcpy(in.local_size, src->local, sizeof in.local_size); in.smem_bytes = src->smem; in.lmem_bytes = src->lmem;
        }
        snprintf(what, sizeof what, "program #%d %s stage", src->serial, s == 5 ? "compute" : s ? "fragment" : "vertex");
        if (!mx_translate(&in, &out)) { printf("nvn_vk: %s: machine code not translated: %s\n", what, out.why); fflush(stdout); }
        else {
            uint64_t spv_hash = 0;
            v->mod = module_from_glsl(s, out.glsl, what, &spv_hash);
            v->cbufs = out.cbufs; v->ssbos = out.ssbos; v->ssbo_w = out.ssbo_written; v->images = out.images; v->in_attr = out.in_attr; v->out_attr = out.out_attr;
            v->dep = s == 0 ? out.int_dep : 0; v->tex_units = out.tex_units; v->uses_alpha = out.uses_alpha; v->nsmp = out.nsmp;
            for (int i = 0; i < out.nsmp && i < 64; i++) {
                const char *ty = out.smp[i].type;
                int arr = strstr(ty, "Array") != NULL, dim = strstr(ty, "Cube") ? (arr ? DIM_CUBEA : DIM_CUBE) : strstr(ty, "3D") ? DIM_3D : strstr(ty, "1D") ? (arr ? DIM_1DA : DIM_1D) : (arr ? DIM_2DA : DIM_2D);
                if (strstr(ty, "MS") || strstr(ty, "Rect") || strstr(ty, "Buffer")) { static char msg[96]; snprintf(msg, sizeof msg, "a shader sampler of type %s", ty); nvn_vk_missing(msg); }
                v->smp[i].unit = out.smp[i].unit; v->smp[i].dim = (uint8_t)dim; v->smp[i].shadow = out.smp[i].shadow; v->smp[i].binding = out.smp[i].binding;
            }
            free(out.glsl);
            v->ok = v->mod != NULL;
            if (v->ok) {                           /* the canonical key: only the bits the code looks at */
                VarRec e;
                v->key[0] &= v->dep; v->key[1] &= v->dep; v->key[2] &= v->tex_units; v->key[3] &= v->tex_units;
                v->h = fnv(fnv(v->hb, v->key, 16), &v->fo, 4);
                memset(&r, 0, sizeof r);
                r.magic = STAGEREC_MAGIC; r.stage = s; r.code_len = v->code_len; memcpy(r.key, v->key, 16); r.fo = v->fo; r.spv = spv_hash; r.hb = v->hb;
                r.cbufs = v->cbufs; r.ssbos = v->ssbos; r.ssbo_w = v->ssbo_w; r.images = v->images; r.dep = v->dep; r.tex_units = v->tex_units; r.in_attr = v->in_attr; r.out_attr = v->out_attr;
                r.uses_alpha = v->uses_alpha; r.nsmp = v->nsmp; memcpy(r.smp, v->smp, sizeof r.smp);
                snprintf(path, sizeof path, "../cache/vk/stage/%d_%016llx.st", s, (unsigned long long)v->h);
                if ((fp = fopen(path, "wb")) != NULL) { fwrite(&r, 1, sizeof r, fp); fclose(fp); }
                memset(&e, 0, sizeof e);
                e.magic = STAGEREC_MAGIC; memcpy(e.key, v->key, 16); e.fo = v->fo; e.dep = v->dep; e.tex = v->tex_units; e.vh = v->h;
                snprintf(path, sizeof path, "../cache/vk/stage/%d_%016llx.var", s, (unsigned long long)v->hb);
                if ((fp = fopen(path, "ab")) != NULL) { fwrite(&e, 1, sizeof e, fp); fclose(fp); }
            }
        }
    }
    EnterCriticalSection(&g_sh_lock);
    if (v->ok) { v->next_h = g_vh[v->h & 4095]; g_vh[v->h & 4095] = v; }
    v->state = 2;
    WakeAllConditionVariable(&g_sh_cv);
    LeaveCriticalSection(&g_sh_lock);
}
/* Any thread: the variant of this code for (key, fo). *how: 0 it was there, 1 made by this call, 2 waited for the thread
 * that was making it. */
static VStage *stage_ensure(const SSrc *src, uint64_t hb, const uint32_t *key, uint32_t fo, int *how) {
    VStage *v, *busy;
    *how = 0;
    EnterCriticalSection(&g_sh_lock);
    for (;;) {
        v = vstage_find(hb, src->stage, src->code_len, key, fo, &busy);
        if (v && v->state == 2) break;
        if (!v) v = busy;
        if (v) { if (!*how) *how = 2; while (v->state < 2) SleepConditionVariableCS(&g_sh_cv, &g_sh_lock, INFINITE); continue; }
        v = vstage_new(hb, src->stage, src->code_len, key, fo);
        LeaveCriticalSection(&g_sh_lock);
        vstage_build(v, src);
        *how = 1;
        EnterCriticalSection(&g_sh_lock);
    }
    LeaveCriticalSection(&g_sh_lock);
    return v;
}
/* Render thread, at a draw or dispatch. */
static VStage *vstage_get(Prog *p, int s, const uint32_t *key, uint32_t fo) {
    Stage *st = &p->st[s];
    VStage *v = st->vk;
    SSrc src;
    int how;
    if (!st->code) return NULL;
    if (v && v->state == 2 && v->fo == fo && key_fits(s, key, v->key, v->dep, v->tex_units)) return v->ok ? v : NULL;
    if (!ssrc_of(&src, p, s)) return NULL;
    LONG64 t0 = tk();
    v = stage_ensure(&src, ssrc_hb(&src), key, fo, &how);
    if (how) { LONG64 dt = tk() - t0; hold_note(how == 1 ? H_STAGE_DRAW : H_STAGE_WAIT, dt); g_tm[6] += dt; }
    st->vk = v; memcpy(v->local, st->local, sizeof v->local);
    return v->ok ? v : NULL;
}

/* ---------------------------------------------------------------- pipelines */
typedef struct { uint32_t vs, fs, chanmask, sample_mask; int32_t cfmt[8], dfmt; uint8_t topo_class, ncolor, samples, poly, a2c, dclamp, logic, sshade, blend_on, pad[3]; uint8_t blend[8][8]; } PKey;
typedef struct Pipe { PKey k; VkPipeline p; VkPipelineLayout layout; VkDescriptorSetLayout dl[2]; int nb[2], push0; VStage *vs, *fs; volatile LONG state; uint8_t recorded, predicted, used; struct Pipe *next; } Pipe;      /* state: 0 queued for a worker, 1 being made, 2 made */
static Pipe *g_pipes[1024];
static void pkey_targets(PKey *k);
static int pkey_targets_of(PKey *k, int ncol, const TargetRef *col, const TargetRef *depth);
static VkBlendFactor blend_factor(unsigned f) {
    static const uint8_t m[9] = {VK_BLEND_FACTOR_SRC_COLOR, VK_BLEND_FACTOR_ONE_MINUS_SRC_COLOR, VK_BLEND_FACTOR_SRC_ALPHA, VK_BLEND_FACTOR_ONE_MINUS_SRC_ALPHA, VK_BLEND_FACTOR_DST_ALPHA, VK_BLEND_FACTOR_ONE_MINUS_DST_ALPHA,
                                 VK_BLEND_FACTOR_DST_COLOR, VK_BLEND_FACTOR_ONE_MINUS_DST_COLOR, VK_BLEND_FACTOR_SRC_ALPHA_SATURATE};
    if (f >= 3 && f <= 0xB) return (VkBlendFactor)m[f - 3];
    switch (f) { case 1: return VK_BLEND_FACTOR_ZERO; case 2: return VK_BLEND_FACTOR_ONE; case 0x10: return VK_BLEND_FACTOR_SRC1_COLOR; case 0x11: return VK_BLEND_FACTOR_ONE_MINUS_SRC1_COLOR; case 0x12: return VK_BLEND_FACTOR_SRC1_ALPHA;
                 case 0x13: return VK_BLEND_FACTOR_ONE_MINUS_SRC1_ALPHA; case 0x61: return VK_BLEND_FACTOR_CONSTANT_COLOR; case 0x62: return VK_BLEND_FACTOR_ONE_MINUS_CONSTANT_COLOR; case 0x63: return VK_BLEND_FACTOR_CONSTANT_ALPHA;
                 case 0x64: return VK_BLEND_FACTOR_ONE_MINUS_CONSTANT_ALPHA; }
    return VK_BLEND_FACTOR_ONE;
}
static VkBlendOp blend_op(unsigned e) { static const uint8_t m[6] = {VK_BLEND_OP_ADD, VK_BLEND_OP_ADD, VK_BLEND_OP_SUBTRACT, VK_BLEND_OP_REVERSE_SUBTRACT, VK_BLEND_OP_MIN, VK_BLEND_OP_MAX}; return (VkBlendOp)m[e < 6 ? e : 1]; }
static void layout_bindings(VStage *v, int s, VkDescriptorSetLayoutBinding *b0, int *n0, VkDescriptorSetLayoutBinding *b1, int *n1) {
    VkFlags sf = s ? VK_SHADER_STAGE_FRAGMENT_BIT : VK_SHADER_STAGE_VERTEX_BIT;
    for (unsigned n = 1; n < 18; n++) if (v->cbufs >> n & 1) { VkDescriptorSetLayoutBinding b = {40u * (unsigned)s + n, VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 1, sf, NULL}; b0[(*n0)++] = b; }
    for (unsigned k = 0; k < 16; k++) if (v->ssbos >> k & 1) { VkDescriptorSetLayoutBinding b = {40u * (unsigned)s + 20 + k, VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 1, sf, NULL}; b0[(*n0)++] = b; }
    for (int i = 0; i < v->nsmp; i++) { VkDescriptorSetLayoutBinding b = {v->smp[i].binding, VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, 1, sf, NULL}; b1[(*n1)++] = b; }
}
static Pipe *pipe_find(const PKey *k, uint64_t h) { for (Pipe *p = g_pipes[h & 1023]; p; p = p->next) if (!memcmp(&p->k, k, sizeof *k)) return p; return NULL; }      /* g_sh_lock held */
static Pipe *pipe_new(const PKey *k, VStage *vs, VStage *fs, uint64_t h, int state) {                                                                                 /* g_sh_lock held */
    Pipe *p = calloc(1, sizeof *p);
    p->k = *k; p->vs = vs; p->fs = fs; p->state = state;
    p->next = g_pipes[h & 1023]; g_pipes[h & 1023] = p;
    return p;
}
/* Makes the pipeline of p->k (any thread, no lock: the device calls are thread-safe, the pipeline cache is synchronised by
 * the driver), then marks it made. Returns the milliseconds it took. */
static double pipe_build(Pipe *p) {
    const PKey *k = &p->k;
    VStage *vs = p->vs, *fs = p->fs;
    LONG64 t0 = tk();
    VkDescriptorSetLayoutBinding b0[80], b1[140];
    layout_bindings(vs, 0, b0, &p->nb[0], b1, &p->nb[1]);
    if (fs) layout_bindings(fs, 1, b0, &p->nb[0], b1, &p->nb[1]);
    for (int i = 0; i < 2; i++) {
        VkDescriptorSetLayoutCreateInfo li = {VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO};
        li.bindingCount = (uint32_t)p->nb[i]; li.pBindings = i ? b1 : b0;
        if (i == 0 && D.has_push && p->nb[0] <= 32) { li.flags = VK_DESCRIPTOR_SET_LAYOUT_CREATE_PUSH_DESCRIPTOR_BIT_KHR; p->push0 = 1; }      /* 32: the smallest maxPushDescriptors a device may have */
        VKC(vkCreateDescriptorSetLayout(V.device, &li, NULL, &p->dl[i]));
    }
    VkPushConstantRange pc = {VK_SHADER_STAGE_VERTEX_BIT | VK_SHADER_STAGE_FRAGMENT_BIT, 0, 16};
    VkPipelineLayoutCreateInfo pl = {VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO};
    pl.setLayoutCount = 2; pl.pSetLayouts = p->dl; pl.pushConstantRangeCount = 1; pl.pPushConstantRanges = &pc;
    VKC(vkCreatePipelineLayout(V.device, &pl, NULL, &p->layout));

    VkPipelineShaderStageCreateInfo st[2];
    memset(st, 0, sizeof st);
    st[0].sType = st[1].sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO;
    st[0].stage = VK_SHADER_STAGE_VERTEX_BIT; st[0].module = vs->mod; st[0].pName = "main";
    st[1].stage = VK_SHADER_STAGE_FRAGMENT_BIT; st[1].module = fs ? fs->mod : NULL; st[1].pName = "main";
    VkPipelineInputAssemblyStateCreateInfo ia = {VK_STRUCTURE_TYPE_PIPELINE_INPUT_ASSEMBLY_STATE_CREATE_INFO};
    ia.topology = k->topo_class == 0 ? VK_PRIMITIVE_TOPOLOGY_POINT_LIST : k->topo_class == 1 ? VK_PRIMITIVE_TOPOLOGY_LINE_LIST : VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST;
    VkPipelineViewportStateCreateInfo vp = {VK_STRUCTURE_TYPE_PIPELINE_VIEWPORT_STATE_CREATE_INFO};
    vp.viewportCount = 1; vp.scissorCount = 1;
    VkPipelineRasterizationProvokingVertexStateCreateInfoEXT pv = {VK_STRUCTURE_TYPE_PIPELINE_RASTERIZATION_PROVOKING_VERTEX_STATE_CREATE_INFO_EXT};
    pv.provokingVertexMode = VK_PROVOKING_VERTEX_MODE_LAST_VERTEX_EXT;
    VkPipelineRasterizationStateCreateInfo rs = {VK_STRUCTURE_TYPE_PIPELINE_RASTERIZATION_STATE_CREATE_INFO};
    rs.polygonMode = D.has_eds3 ? VK_POLYGON_MODE_FILL : k->poly == 0 ? VK_POLYGON_MODE_POINT : k->poly == 1 ? VK_POLYGON_MODE_LINE : VK_POLYGON_MODE_FILL; rs.depthClampEnable = k->dclamp; rs.lineWidth = 1.0f;
    if (D.has_pv) rs.pNext = &pv;
    VkPipelineMultisampleStateCreateInfo ms = {VK_STRUCTURE_TYPE_PIPELINE_MULTISAMPLE_STATE_CREATE_INFO};
    VkSampleMask smask = D.has_eds3 ? 0xffffffffu : k->sample_mask;
    ms.rasterizationSamples = (VkSampleCountFlagBits)(k->samples ? k->samples : 1); ms.alphaToCoverageEnable = k->a2c; ms.pSampleMask = &smask;
    if (k->sshade == 1 && D.f2.features.sampleRateShading) { ms.sampleShadingEnable = VK_TRUE; ms.minSampleShading = 1.0f; }
    VkPipelineDepthStencilStateCreateInfo ds = {VK_STRUCTURE_TYPE_PIPELINE_DEPTH_STENCIL_STATE_CREATE_INFO};
    ds.maxDepthBounds = 1.0f;
    VkPipelineColorBlendAttachmentState ba[8];
    memset(ba, 0, sizeof ba);
    for (int i = 0; i < k->ncolor; i++) {
        const uint8_t *b = k->blend[i];
        ba[i].blendEnable = k->blend_on >> i & 1; ba[i].colorWriteMask = D.has_eds3 ? 15 : (k->chanmask >> (i * 4)) & 15;
        ba[i].srcColorBlendFactor = blend_factor(b[0]); ba[i].dstColorBlendFactor = blend_factor(b[1]); ba[i].srcAlphaBlendFactor = blend_factor(b[2]); ba[i].dstAlphaBlendFactor = blend_factor(b[3]);
        ba[i].colorBlendOp = blend_op(b[4]); ba[i].alphaBlendOp = blend_op(b[5]);
    }
    VkPipelineColorBlendStateCreateInfo cb = {VK_STRUCTURE_TYPE_PIPELINE_COLOR_BLEND_STATE_CREATE_INFO};
    cb.attachmentCount = k->ncolor; cb.pAttachments = ba;
    if (k->logic != 3 && D.f2.features.logicOp) { cb.logicOpEnable = VK_TRUE; cb.logicOp = (VkLogicOp)(k->logic & 15); }
    VkDynamicState dyn[32] = {VK_DYNAMIC_STATE_VIEWPORT, VK_DYNAMIC_STATE_SCISSOR, VK_DYNAMIC_STATE_LINE_WIDTH, VK_DYNAMIC_STATE_DEPTH_BIAS, VK_DYNAMIC_STATE_BLEND_CONSTANTS, VK_DYNAMIC_STATE_STENCIL_COMPARE_MASK,
        VK_DYNAMIC_STATE_STENCIL_WRITE_MASK, VK_DYNAMIC_STATE_STENCIL_REFERENCE, VK_DYNAMIC_STATE_CULL_MODE, VK_DYNAMIC_STATE_FRONT_FACE, VK_DYNAMIC_STATE_PRIMITIVE_TOPOLOGY, VK_DYNAMIC_STATE_DEPTH_TEST_ENABLE,
        VK_DYNAMIC_STATE_DEPTH_WRITE_ENABLE, VK_DYNAMIC_STATE_DEPTH_COMPARE_OP, VK_DYNAMIC_STATE_STENCIL_TEST_ENABLE, VK_DYNAMIC_STATE_STENCIL_OP, VK_DYNAMIC_STATE_DEPTH_BIAS_ENABLE, VK_DYNAMIC_STATE_PRIMITIVE_RESTART_ENABLE,
        VK_DYNAMIC_STATE_RASTERIZER_DISCARD_ENABLE, VK_DYNAMIC_STATE_VERTEX_INPUT_EXT};
    uint32_t ndyn = 20;
    if (D.has_eds3) {
        dyn[ndyn++] = VK_DYNAMIC_STATE_COLOR_BLEND_ENABLE_EXT; dyn[ndyn++] = VK_DYNAMIC_STATE_COLOR_BLEND_EQUATION_EXT; dyn[ndyn++] = VK_DYNAMIC_STATE_COLOR_WRITE_MASK_EXT; dyn[ndyn++] = VK_DYNAMIC_STATE_POLYGON_MODE_EXT;
        dyn[ndyn++] = VK_DYNAMIC_STATE_ALPHA_TO_COVERAGE_ENABLE_EXT; dyn[ndyn++] = VK_DYNAMIC_STATE_SAMPLE_MASK_EXT;
        if (D.f2.features.depthClamp) dyn[ndyn++] = VK_DYNAMIC_STATE_DEPTH_CLAMP_ENABLE_EXT;
    }
    VkPipelineDynamicStateCreateInfo dy = {VK_STRUCTURE_TYPE_PIPELINE_DYNAMIC_STATE_CREATE_INFO};
    dy.dynamicStateCount = ndyn; dy.pDynamicStates = dyn;
    VkPipelineRenderingCreateInfo ri = {VK_STRUCTURE_TYPE_PIPELINE_RENDERING_CREATE_INFO};
    VkFormat cf[8];
    for (int i = 0; i < 8; i++) cf[i] = (VkFormat)k->cfmt[i];
    ri.colorAttachmentCount = k->ncolor; ri.pColorAttachmentFormats = cf;
    if (fmt_aspect((VkFormat)k->dfmt) & VK_IMAGE_ASPECT_DEPTH_BIT) ri.depthAttachmentFormat = (VkFormat)k->dfmt;
    if (k->dfmt && (fmt_aspect((VkFormat)k->dfmt) & VK_IMAGE_ASPECT_STENCIL_BIT)) ri.stencilAttachmentFormat = (VkFormat)k->dfmt;
    VkGraphicsPipelineCreateInfo gi = {VK_STRUCTURE_TYPE_GRAPHICS_PIPELINE_CREATE_INFO};
    gi.pNext = &ri; gi.stageCount = fs ? 2 : 1; gi.pStages = st; gi.pInputAssemblyState = &ia; gi.pViewportState = &vp; gi.pRasterizationState = &rs; gi.pMultisampleState = &ms;
    gi.pDepthStencilState = &ds; gi.pColorBlendState = &cb; gi.pDynamicState = &dy; gi.layout = p->layout;
    VkResult r = vkCreateGraphicsPipelines(V.device, g_pcache, 1, &gi, NULL, &p->p);
    if (r != VK_SUCCESS) vkd_fail("vkCreateGraphicsPipelines (vertex stage %u, fragment stage %u, %d colour targets, depth format %d): %s", k->vs, k->fs, k->ncolor, k->dfmt, vk_result_name(r));
    InterlockedIncrement64(&R.pipelines);
    EnterCriticalSection(&g_sh_lock);
    p->state = 2;
    WakeAllConditionVariable(&g_sh_cv);
    LeaveCriticalSection(&g_sh_lock);
    { LARGE_INTEGER fq; QueryPerformanceFrequency(&fq); return (double)(tk() - t0) * 1000.0 / (double)fq.QuadPart; }
}
/* ..\cache\vk\pipes.bin: every pipeline key a draw on this PC ever USED, with its stages named by their variant hashes.
 * Read at start by the workers. A predicted pipeline is written here only when a draw uses it. */
typedef struct { uint32_t magic, compute; uint64_t vs_h, fs_h; PKey k; } PipeRec;
#define PIPEREC_MAGIC (0x31455049u + MX_VK_VERSION)
static void piperec_append(const PKey *k, VStage *vs, VStage *fs, int compute) {
    PipeRec r;
    memset(&r, 0, sizeof r);
    r.magic = PIPEREC_MAGIC; r.compute = (uint32_t)compute; r.vs_h = vs->h; r.fs_h = fs ? fs->h : 0;
    if (k) { r.k = *k; r.k.vs = r.k.fs = 0; }
    FILE *fp = fopen("../cache/vk/pipes.bin", "ab");
    if (fp) { fwrite(&r, 1, sizeof r, fp); fclose(fp); }
}

/* ---- prediction: pass signatures seen so far, and the stage pairs the game handed over */
typedef struct { PKey k; int uses; } Sig;          /* k with vs = fs = 0, triangles, no sample shading */
typedef struct PairRec { VStage *vs, *fs; uint8_t drawn, npred, sshade; int16_t cont; uint64_t sigs, used; struct PairRec *next, *all; } PairRec;      /* cont: 1 + index of the shader container the pair was found in (session 6), used: the pass signatures draws used it with */
static Sig g_sig[64];
static int g_nsig, g_predict;
static PairRec *g_pair_tab[1024], *g_pair_all;
static PairRec *pair_get(VStage *vs, VStage *fs) {                 /* g_sh_lock held */
    unsigned h = (vs->id * 2654435761u ^ (fs ? fs->id * 40503u : 0)) & 1023;
    PairRec *r;
    for (r = g_pair_tab[h]; r; r = r->next) if (r->vs == vs && r->fs == fs) return r;
    r = calloc(1, sizeof *r);
    r->vs = vs; r->fs = fs; r->next = g_pair_tab[h]; g_pair_tab[h] = r; r->all = g_pair_all; g_pair_all = r;
    return r;
}
static int sig_note(const PKey *k, int *idx) {     /* g_sh_lock held: the index of the signature when it is NEW, else -1; *idx: its index either way (-1: table full) */
    PKey s = *k;
    s.vs = s.fs = 0; s.topo_class = 2; s.sshade = 0;
    for (int i = 0; i < g_nsig; i++) if (!memcmp(&g_sig[i].k, &s, sizeof s)) { g_sig[i].uses++; *idx = i; return -1; }
    *idx = -1;
    if (g_nsig == 64) return -1;
    g_sig[g_nsig].k = s; g_sig[g_nsig].uses = 1;
    *idx = g_nsig;
    return g_nsig++;
}
static void cont_learn(PairRec *pr);
/* ---- the job queue of the workers */
typedef struct Job { struct Job *next; int kind, sshade, cont, has[3]; Pipe *pipe; PKey k; uint32_t key0[4], key1[4]; SSrc src[3]; uint8_t data[1]; } Job;      /* kind: 0 a program handed over, 1 one pipeline, 2 the stages and the pipeline of a draw the look-ahead met */
static Job *g_jq_head, *g_jq_tail, *g_bq_head, *g_bq_tail;      /* g_bq: the background queue (container scan, session 6): taken only when g_jq is empty */
static LONG64 g_jq_queued, g_jq_done, g_bq_queued, g_bq_done;
static void job_push_bg(Job *j) {                  /* g_sh_lock held */
    j->next = NULL;
    if (g_bq_tail) g_bq_tail->next = j; else g_bq_head = j;
    g_bq_tail = j; g_bq_queued++;
    WakeConditionVariable(&g_jq_cv);
}
static int g_m4_on, g_m4_quit, g_scan_on;
static LONG64 g_scan_jobs, g_scan_pipes, g_cs_pairs;
static volatile LONG g_in_fight;
static struct { int w, h, ncol, cf, df, lv; long long n, fight, first; } g_rtlog[256];      /* SSBU_VK_RTLOG=1: render-target sizes (nvn_vk_draw.c, where a pass begins) */
static int g_rtlog_n;
static int g_ncont, g_cscan, g_cscan_log, g_cpredict, g_game_tables = 1;     /* the container scan (end of this file) */
static LONG64 g_cs_scans, g_cs_vars, g_cs_jobs, g_cs_tk, g_cs_pred, g_cs_bytes;
static uint64_t g_cscan_reach = 64, g_cscan_step = 0x1000;    /* MB searched below a control section for the header of its container, and the alignment a header is looked for at (SSBU_VK_CSCAN_STEP) */
static void job_push(Job *j) {                     /* g_sh_lock held */
    j->next = NULL;
    if (g_jq_tail) g_jq_tail->next = j; else g_jq_head = j;
    g_jq_tail = j; g_jq_queued++;
    WakeConditionVariable(&g_jq_cv);
}
static void job_push_front(Job *j) {               /* g_sh_lock held: needed by the batch about to be replayed */
    j->next = g_jq_head;
    g_jq_head = j;
    if (!g_jq_tail) g_jq_tail = j;
    g_jq_queued++;
    WakeConditionVariable(&g_jq_cv);
}
static void job_copy_src(Job *j, uint8_t **d, int i, const SSrc *s) {
    j->has[i] = 1; j->src[i] = *s;
    memcpy(*d, s->code, (size_t)s->code_len); j->src[i].code = *d; *d += (s->code_len + 7) & ~7;
    if (s->cdata) { memcpy(*d, s->cdata, s->cdata_size); j->src[i].cdata = *d; *d += (s->cdata_size + 7) & ~7u; }
}
/* g_sh_lock held: queues the pipeline of this pair for signature i, unless the pair was already drawn, has had its three
 * predictions, or the pipeline exists. */
static void predict_pair(PairRec *pr, int i) {
    if (pr->drawn || pr->npred >= 3 || (pr->sigs >> i & 1)) return;
    PKey k = g_sig[i].k;
    k.vs = pr->vs->id; k.fs = pr->fs ? pr->fs->id : 0; k.sshade = pr->fs ? pr->sshade : 0;
    uint64_t h = fnv(0xcbf29ce484222325ULL, &k, sizeof k);
    pr->sigs |= 1ull << i;
    if (pipe_find(&k, h)) return;
    pr->npred++;
    Job *j = calloc(1, sizeof *j);
    j->kind = 1; j->pipe = pipe_new(&k, pr->vs, pr->fs, h, 0); j->pipe->predicted = 1;
    g_pred_made++;
    job_push(j);
}
/* Render thread, at a draw: the pipeline of the key; made here, or waited for, when it is not ready (the frame is late). */
static Pipe *pipe_get(const PKey *k, VStage *vs, VStage *fs) {
    uint64_t h = fnv(0xcbf29ce484222325ULL, k, sizeof *k);
    int mine = 0, waited = 0;
    LONG64 t0 = 0;
    EnterCriticalSection(&g_sh_lock);
    Pipe *p = pipe_find(k, h);
    if (!p) { p = pipe_new(k, vs, fs, h, 1); mine = 1; }
    else if (p->state == 0) { p->state = 1; mine = 1; }          /* queued, no worker has begun: made here rather than waited for behind the queue */
    else if (p->state == 1) { waited = 1; t0 = tk(); while (p->state < 2) SleepConditionVariableCS(&g_sh_cv, &g_sh_lock, INFINITE); }
    if (!p->used) {
        int idx, i = sig_note(k, &idx);
        PairRec *pr0 = pair_get(vs, fs);
        pr0->drawn = 1;
        if (idx >= 0) { pr0->used |= 1ull << idx; cont_learn(pr0); }
        if (i >= 0 && g_predict) for (PairRec *pr = g_pair_all; pr; pr = pr->all) predict_pair(pr, i);      /* a pass signature never seen: the pairs not yet drawn get it now, on the workers */
    }
    LeaveCriticalSection(&g_sh_lock);
    if (waited) { LONG64 dt = tk() - t0; hold_note(H_PIPE_WAIT, dt); g_tm[5] += dt; }
    if (mine) {
        t0 = tk();
        double ms = pipe_build(p);
        LONG64 dt = tk() - t0;
        hold_note(H_PIPE_DRAW, dt); g_tm[5] += dt;
        g_pipe_miss++;
        if (D.debug) printf("nvn_vk: pipeline made at a draw (%lld): stages %u/%u, class %d, %d colour (format %d), depth %d, samples %d: %.1f ms\n", (long long)g_pipe_miss, k->vs, k->fs, k->topo_class, k->ncolor, k->cfmt[0], k->dfmt, k->samples, ms);
    }
    if (!p->used) {
        p->used = 1;
        if (p->predicted && !mine) g_pred_used++;
        if (!p->recorded) { piperec_append(k, vs, fs, 0); p->recorded = 1; }
    }
    return p;
}
/* Any thread: the compute pipeline of a stage. Returns 1 when this call made it, 2 when it waited for another thread, 0 when it was there. */
static int compute_pipe_ensure(VStage *v) {
    int how = 0;
    if (v->cp_state == 2) return 0;
    EnterCriticalSection(&g_sh_lock);
    if (v->cp_state == 0) { v->cp_state = 1; how = 1; }
    else if (v->cp_state == 1) { how = 2; while (v->cp_state < 2) SleepConditionVariableCS(&g_sh_cv, &g_sh_lock, INFINITE); }
    LeaveCriticalSection(&g_sh_lock);
    if (how == 1) {
        compute_pipe_make(v);
        EnterCriticalSection(&g_sh_lock);
        v->cp_state = 2;
        WakeAllConditionVariable(&g_sh_cv);
        LeaveCriticalSection(&g_sh_lock);
    }
    return how;
}

/* ---------------------------------------------------------------- the workers */
static HANDLE g_pw_thread[16], g_pw_gate;
static int g_pw_nthread, g_pw_n, g_pw_waited;
typedef struct { uint32_t magic, compute; uint64_t vs_h, fs_h; PKey k; } PipeRecIn;
static PipeRec *g_pw_rec;
static volatile LONG g_pw_next, g_pw_left;
static LONG64 g_pw_t0, g_pw_t1;
static char g_pcache_path[160];
static VStage *pw_stage(int s, uint64_t vh) {      /* g_sh_lock held: a variant named by pipes.bin, from its record */
    StageRec r;
    VkShaderModule mod;
    for (VStage *v = g_vh[vh & 4095]; v; v = v->next_h) if (v->h == vh && v->stage == s) return v;
    if (!stage_rec_read(s, vh, &r) || !(mod = module_from_spv(r.spv))) return NULL;
    VStage *v = vstage_new(r.hb, s, r.code_len, r.key, r.fo);
    vstage_from_rec(v, &r, vh, mod);
    v->next_h = g_vh[vh & 4095]; g_vh[vh & 4095] = v; v->state = 2;
    InterlockedIncrement64(&R.modules); InterlockedIncrement64(&g_pw_stages);
    return v;
}
/* A worker that is about to make a vertex stage gives the fragment stage of the same program to another worker first
 * (kind 3), so that a program created in the middle of a fight costs the longer of the two stages, not their sum. */
static void spawn_stage(const SSrc *src, const uint32_t *key) {
    Job *j = calloc(1, sizeof *j + (size_t)src->code_len + src->cdata_size + 16);
    uint8_t *d = j->data;
    j->kind = 3; memcpy(j->key1, key, 16);
    job_copy_src(j, &d, 1, src);
    EnterCriticalSection(&g_sh_lock);
    job_push_front(j);
    LeaveCriticalSection(&g_sh_lock);
}
static void job_prog(Job *j) {
    static const uint32_t zero[4];
    int how;
    InterlockedIncrement64(&g_w_progs);
    if (j->has[0] && j->has[1]) spawn_stage(&j->src[1], zero);
    if (j->has[2]) {
        VStage *c = stage_ensure(&j->src[2], ssrc_hb(&j->src[2]), zero, 0, &how);
        if (how == 1) InterlockedIncrement64(&g_w_stages);
        if (!g_offline && c->ok && !c->images && c->nsmp <= 32) compute_pipe_ensure(c);
    }
    if (!j->has[0]) return;
    uint64_t hv = ssrc_hb(&j->src[0]);
    VStage *vs = stage_ensure(&j->src[0], hv, zero, 0, &how), *fs = NULL;
    if (how == 1) InterlockedIncrement64(&g_w_stages);
    if (j->has[1]) { fs = stage_ensure(&j->src[1], ssrc_hb(&j->src[1]), zero, 0, &how); if (how == 1) InterlockedIncrement64(&g_w_stages); }
    if (!vs->ok || (fs && !fs->ok)) return;
    if (fs && (fs->in_attr & ~vs->out_attr)) {    /* fragment inputs the vertex code never writes: the variant that declares them */
        vs = stage_ensure(&j->src[0], hv, zero, fs->in_attr & ~vs->out_attr, &how);
        if (how == 1) InterlockedIncrement64(&g_w_stages);
        if (!vs->ok) return;
    }
    if (j->cont) {                                 /* found by the container scan: the pair belongs to that container */
        EnterCriticalSection(&g_sh_lock);
        PairRec *pc = pair_get(vs, fs);
        if (!pc->cont) { pc->cont = (int16_t)j->cont; g_cs_pairs++; }
        cont_learn(pc);
        LeaveCriticalSection(&g_sh_lock);
    }
    if (!g_predict) return;
    EnterCriticalSection(&g_sh_lock);
    PairRec *pr = pair_get(vs, fs);
    pr->sshade = (uint8_t)j->sshade;
    for (int n = 0; n < 3 && !pr->drawn; n++) {    /* the three signatures most used so far */
        int best = -1;
        for (int i = 0; i < g_nsig; i++) if (!(pr->sigs >> i & 1) && (best < 0 || g_sig[i].uses > g_sig[best].uses)) best = i;
        if (best < 0) break;
        predict_pair(pr, best);
    }
    LeaveCriticalSection(&g_sh_lock);
}
static void job_draw(Job *j) {                     /* a draw the look-ahead met whose stages were not all made yet */
    int how;
    VStage *fs = NULL;
    if (j->has[1]) spawn_stage(&j->src[1], j->key1);
    uint64_t hv = ssrc_hb(&j->src[0]);
    VStage *vs = stage_ensure(&j->src[0], hv, j->key0, 0, &how);
    if (how == 1) InterlockedIncrement64(&g_w_stages);
    if (j->has[1]) { fs = stage_ensure(&j->src[1], ssrc_hb(&j->src[1]), j->key1, 0, &how); if (how == 1) InterlockedIncrement64(&g_w_stages); if (!fs->ok) return; }
    if (!vs->ok) return;
    if (fs && (fs->in_attr & ~vs->out_attr)) { vs = stage_ensure(&j->src[0], hv, j->key0, fs->in_attr & ~vs->out_attr, &how); if (how == 1) InterlockedIncrement64(&g_w_stages); if (!vs->ok) return; }
    if (!D.has_eds3) return;                       /* the key holds blend state the look-ahead does not follow */
    PKey k = j->k;
    k.vs = vs->id; k.fs = fs ? fs->id : 0;
    uint64_t h = fnv(0xcbf29ce484222325ULL, &k, sizeof k);
    int mine = 0;
    EnterCriticalSection(&g_sh_lock);
    Pipe *p = pipe_find(&k, h);
    if (!p) { p = pipe_new(&k, vs, fs, h, 1); mine = 1; } else if (p->state == 0) { p->state = 1; mine = 1; }
    LeaveCriticalSection(&g_sh_lock);
    if (mine) { pipe_build(p); InterlockedIncrement64(&g_w_pipes); }
}
static DWORD WINAPI pw_main(void *arg) {
    (void)arg;
    for (;;) {                                     /* 1. the keys of earlier runs */
        LONG i = InterlockedIncrement(&g_pw_next) - 1;
        if (i >= g_pw_n) break;
        PipeRec *r = &g_pw_rec[i];
        EnterCriticalSection(&g_sh_lock);
        VStage *vs = pw_stage(r->compute ? 5 : 0, r->vs_h), *fs = r->fs_h ? pw_stage(1, r->fs_h) : NULL;
        Pipe *p = NULL;
        if (vs && !r->compute && (!r->fs_h || fs)) {
            r->k.vs = vs->id; r->k.fs = fs ? fs->id : 0;
            uint64_t h = fnv(0xcbf29ce484222325ULL, &r->k, sizeof r->k);
            if (!pipe_find(&r->k, h)) { p = pipe_new(&r->k, vs, fs, h, 1); p->recorded = 1; }
            int idx;
            sig_note(&r->k, &idx);
            PairRec *pr0 = pair_get(vs, fs);
            pr0->drawn = 1;                        /* a pair with recorded keys needs no prediction */
            if (idx >= 0) pr0->used |= 1ull << idx;
        }
        LeaveCriticalSection(&g_sh_lock);
        if (!vs || (r->fs_h && !fs)) { InterlockedIncrement64(&g_pw_failed); continue; }      /* a stage record or SPIR-V file is gone: made when the game hands the program over, as on a first run */
        if (r->compute) { vs->cp_recorded = 1; if (compute_pipe_ensure(vs) == 1) InterlockedIncrement64(&g_pw_pipes); continue; }
        if (p) { pipe_build(p); InterlockedIncrement64(&g_pw_pipes); }
    }
    InterlockedExchange64(&g_pw_t1, tk());
    if (InterlockedDecrement(&g_pw_left) == 0) SetEvent(g_pw_gate);
    for (;;) {                                     /* 2. what the game hands over while it runs */
        EnterCriticalSection(&g_sh_lock);
        while (!g_jq_head && !g_bq_head && !g_m4_quit) SleepConditionVariableCS(&g_jq_cv, &g_sh_lock, INFINITE);
        Job *j = g_jq_head;
        int bg = 0;
        if (j) { g_jq_head = j->next; if (!g_jq_head) g_jq_tail = NULL; }
        else if (!g_m4_quit && (j = g_bq_head) != NULL) { g_bq_head = j->next; if (!g_bq_head) g_bq_tail = NULL; bg = 1; }      /* at exit the background work is left undone */
        Pipe *p = NULL;
        if (j && j->kind == 1 && j->pipe->state == 0) { p = j->pipe; p->state = 1; }
        LeaveCriticalSection(&g_sh_lock);
        if (!j) break;
        if (j->kind == 0) job_prog(j);
        else if (j->kind == 2) job_draw(j);
        else if (j->kind == 3) { int how; stage_ensure(&j->src[1], ssrc_hb(&j->src[1]), j->key1, 0, &how); if (how == 1) InterlockedIncrement64(&g_w_stages); }
        else if (p) { pipe_build(p); InterlockedIncrement64(&g_w_pipes); }
        free(j);
        EnterCriticalSection(&g_sh_lock);
        if (bg) g_bq_done++; else g_jq_done++;
        WakeAllConditionVariable(&g_sh_cv);
        LeaveCriticalSection(&g_sh_lock);
    }
    return 0;
}
/* nvnProgramSetShaders, GUEST thread (called by the front end when the renderer is Vulkan): the program's stages go to
 * the workers now. The caller is held only while more jobs wait than there are workers (a burst of a loading thread),
 * so that loading ends when its shaders are ready; a single program created during a fight does not hold its caller. */
void nvn_vk_program_set(void *prog) {
    Prog *p = prog;
    SSrc s[3];
    if (!g_m4_on || p->st[2].state || p->st[3].state || p->st[4].state) return;
    int has[3] = {ssrc_of(&s[0], p, 0), ssrc_of(&s[1], p, 1), ssrc_of(&s[2], p, 5)};
    if (!has[0] && !has[2]) return;
    size_t need = 0;
    for (int i = 0; i < 3; i++) if (has[i]) need += (size_t)s[i].code_len + s[i].cdata_size + 16;
    Job *j = calloc(1, sizeof *j + need);
    uint8_t *d = j->data;
    j->sshade = p->sample_shading;
    for (int i = 0; i < 3; i++) if (has[i]) job_copy_src(j, &d, i, &s[i]);
    EnterCriticalSection(&g_sh_lock);
    job_push(j);
    /* session 6: outside a fight (no compute dispatch in the last frame) the caller is also held while the container scan
     * still has work: loading ends when everything the container holds is ready */
    if (g_jq_queued - g_jq_done > g_pw_nthread || (!g_in_fight && g_bq_queued > g_bq_done)) {
        LONG64 t0 = tk();
        LARGE_INTEGER fq; QueryPerformanceFrequency(&fq);
        while ((g_jq_queued - g_jq_done > g_pw_nthread || (!g_in_fight && g_bq_queued > g_bq_done)) && tk() - t0 < 30 * fq.QuadPart) SleepConditionVariableCS(&g_sh_cv, &g_sh_lock, 100);
        g_set_held++; g_set_held_tk += tk() - t0;
    }
    LeaveCriticalSection(&g_sh_lock);
}
static int piperec_cmp(const void *a, const void *b) { return memcmp(a, b, sizeof(PipeRec)); }
static void prewarm_start(void) {
    InitializeCriticalSection(&g_sh_lock);
    InitializeConditionVariable(&g_sh_cv); InitializeConditionVariable(&g_jq_cv);
    CreateDirectoryA("../cache/vk", NULL); CreateDirectoryA("../cache/vk/spv", NULL); CreateDirectoryA("../cache/vk/stage", NULL);
    {   HMODULE m = LoadLibraryA("ssbu_glslang.dll");
        g_glsl_to_spirv = m ? (void *)GetProcAddress(m, "ssbu_glsl_to_spirv") : NULL; g_spirv_free = m ? (void *)GetProcAddress(m, "ssbu_spirv_free") : NULL;
        if (!g_glsl_to_spirv || !g_spirv_free) vkd_fail("ssbu_glslang.dll cannot be loaded (build_glslang.bat makes it)");
    }
    {   /* the driver's pipeline cache, ours on disk: keyed by GPU and driver version (the driver checks its own header too) */
        VkPipelineCacheCreateInfo ci = {VK_STRUCTURE_TYPE_PIPELINE_CACHE_CREATE_INFO};
        void *data = NULL;
        snprintf(g_pcache_path, sizeof g_pcache_path, "../cache/vk/pipelines_%04x_%04x_%08x.bin", (unsigned)V.props.vendorID, (unsigned)V.props.deviceID, (unsigned)V.props.driverVersion);
        FILE *fp = fopen(g_pcache_path, "rb");
        if (fp) { fseek(fp, 0, SEEK_END); long n = ftell(fp); fseek(fp, 0, SEEK_SET); if (n > 0 && (data = malloc((size_t)n)) && fread(data, 1, (size_t)n, fp) == (size_t)n) { ci.initialDataSize = (size_t)n; ci.pInitialData = data; } fclose(fp); }
        if (vkCreatePipelineCache(V.device, &ci, NULL, &g_pcache) != VK_SUCCESS) { ci.initialDataSize = 0; ci.pInitialData = NULL; VKC(vkCreatePipelineCache(V.device, &ci, NULL, &g_pcache)); }
        printf("nvn_vk: pipeline cache %s: %llu KB read\n", g_pcache_path, (unsigned long long)(ci.initialDataSize >> 10));
        free(data);
    }
    /* Blind prediction (pair x most used pass signatures) is OFF unless SSBU_VK_PREDICT=1: measured on a first run it made
     * 8,418 pipelines of which draws used 324, and kept the workers from the programs being handed over. The look-ahead
     * (scan_list below) names exactly what a batch needs instead. */
    g_predict = D.has_eds3 && getenv("SSBU_VK_PREDICT") && atoi(getenv("SSBU_VK_PREDICT"));
    g_scan_on = D.has_eds3 && !(getenv("SSBU_VK_LOOKAHEAD") && !atoi(getenv("SSBU_VK_LOOKAHEAD")));
    g_cscan = !(getenv("SSBU_VK_CSCAN") && !atoi(getenv("SSBU_VK_CSCAN")));                              /* session 6: the container scan */
    g_cpredict = D.has_eds3 && !(getenv("SSBU_VK_CPREDICT") && !atoi(getenv("SSBU_VK_CPREDICT")));      /* and the pipelines of a container's pass signatures for all its pairs */
    g_cscan_log = getenv("SSBU_VK_CSCAN_LOG") && atoi(getenv("SSBU_VK_CSCAN_LOG"));
    if (getenv("SSBU_VK_CSCAN_STEP") && atoi(getenv("SSBU_VK_CSCAN_STEP")) >= 8) g_cscan_step = (uint64_t)atoi(getenv("SSBU_VK_CSCAN_STEP")) & ~7ull;
    if (getenv("SSBU_VK_CSCAN_REACH") && atoi(getenv("SSBU_VK_CSCAN_REACH")) > 0) g_cscan_reach = (uint64_t)atoi(getenv("SSBU_VK_CSCAN_REACH"));
    int ahead = !(getenv("SSBU_VK_PREWARM") && !atoi(getenv("SSBU_VK_PREWARM")));
    FILE *fp = ahead ? fopen("../cache/vk/pipes.bin", "rb") : NULL;
    if (fp) {
        fseek(fp, 0, SEEK_END); long n = ftell(fp); fseek(fp, 0, SEEK_SET);
        g_pw_rec = malloc((size_t)n + 1);
        g_pw_n = (int)(fread(g_pw_rec, sizeof(PipeRec), (size_t)n / sizeof(PipeRec), fp));
        fclose(fp);
        int kept = 0;
        qsort(g_pw_rec, (size_t)g_pw_n, sizeof(PipeRec), piperec_cmp);
        for (int i = 0; i < g_pw_n; i++) if (g_pw_rec[i].magic == PIPEREC_MAGIC && (!kept || memcmp(&g_pw_rec[kept - 1], &g_pw_rec[i], sizeof(PipeRec)))) g_pw_rec[kept++] = g_pw_rec[i];
        g_pw_n = kept;
    } else printf(ahead ? "nvn_vk: no ../cache/vk/pipes.bin: a first run on this PC; stages and pipelines are made when the game hands its programs over\n" : "nvn_vk: SSBU_VK_PREWARM=0: the pipeline list of earlier runs is not read\n");
    SYSTEM_INFO si;
    GetSystemInfo(&si);
    g_pw_nthread = (int)si.dwNumberOfProcessors - 2;
    if (g_pw_nthread < 1) g_pw_nthread = 1;
    if (g_pw_nthread > 16) g_pw_nthread = 16;
    if (getenv("SSBU_VK_WORKERS") && atoi(getenv("SSBU_VK_WORKERS")) > 0 && atoi(getenv("SSBU_VK_WORKERS")) <= 16) g_pw_nthread = atoi(getenv("SSBU_VK_WORKERS"));
    g_pw_gate = CreateEventA(NULL, TRUE, FALSE, NULL);
    g_pw_left = g_pw_nthread;
    g_pw_t0 = tk();
    for (int i = 0; i < g_pw_nthread; i++) g_pw_thread[i] = CreateThread(NULL, 0, pw_main, NULL, 0, NULL);
    g_m4_on = !(getenv("SSBU_VK_HANDOVER") && !atoi(getenv("SSBU_VK_HANDOVER")));
    printf("nvn_vk: %d pipelines listed in ../cache/vk/pipes.bin; %d worker threads; programs are handed to them when the game sets their shaders: %s; key prediction: %s\n", g_pw_n, g_pw_nthread,
           g_m4_on ? "yes" : "no (SSBU_VK_HANDOVER=0)", g_predict ? "blind (SSBU_VK_PREDICT=1)" : g_scan_on ? "look-ahead of every batch" : D.has_eds3 ? "none (SSBU_VK_LOOKAHEAD=0)" : "none (blend state is part of the key on this GPU)");
}
/* ---------------------------------------------------------------- look-ahead: what a batch will draw, before it is replayed
 * The lists of a submitted batch are read once for the (stage pair, pass formats, topology class) of every draw. A
 * combination not met before whose stages or pipeline do not exist goes to the FRONT of the worker queue; the replay that
 * follows then finds them made, waits for the one being made, or makes a queued one itself: the work of a frame that needs
 * many new pipelines at once (the first frame of a fight) is spread over all cores instead of done one by one at the draws.
 * Not followed: integer texture formats (taken as bound now) and, without extended dynamic state 3, anything. */
typedef struct { Prog *prog[2]; int ncol, nattr, sig_ok, attr_new; TargetRef col[8], depth; uint32_t vattr[32], ints, sints, sig_tag; uint8_t logic; PKey sig; } Scan;
static uint64_t g_scan_seen[8192];
static void scan_sig(Scan *s) {
    memset(&s->sig, 0, sizeof s->sig);
    s->sig_ok = pkey_targets_of(&s->sig, s->ncol, s->col, &s->depth) && (s->ncol || s->depth.tex);
    s->sig_tag = (uint32_t)fnv(0xcbf29ce484222325ULL, &s->sig, sizeof s->sig);
}
static void scan_begin(Scan *s) {
    s->prog[0] = R.prog[0]; s->prog[1] = R.prog[1]; s->ncol = R.ncol; memcpy(s->col, R.col, sizeof s->col); s->depth = R.depth;
    s->nattr = R.nattr; memcpy(s->vattr, R.vattr, sizeof s->vattr); s->attr_new = 1; s->logic = R.logic;
    scan_sig(s);
}
static void scan_draw(Scan *s, unsigned prim) {
    static const uint8_t tclass[7] = {0, 1, 1, 1, 2, 2, 2};
    Prog *p0 = s->prog[0], *p1 = s->prog[1];
    if (!p0 || prim > 6 || !s->sig_ok || !p0->st[0].code || (p1 && !p1->st[1].code) || p0->dead || (p1 && p1->dead)) return;
    if (s->attr_new) {                             /* which attributes are integers (as draw_prepare) */
        s->ints = s->sints = 0; s->attr_new = 0;
        for (int i = 0; i < 16 && i < s->nattr; i++) {
            int nf = (int)(s->vattr[i] & 0xff), k = nf >= 0x6D ? nf - 0x6D : (nf - 1) % 12;
            if (((nf >= 1 && nf <= 0x30) || (nf >= 0x6D && nf <= 0x78)) && (k == 2 || k == 3 || k == 7 || k == 8 || k == 10 || k == 11)) { s->ints |= 1u << i; if (k == 3 || k == 8 || k == 11) s->sints |= 1u << i; }
            if (nf == 0x3E) s->ints |= 1u << i;
            if (nf == 0x6A) { s->ints |= 1u << i; s->sints |= 1u << i; }
        }
    }
    uint64_t w[6] = {(uint64_t)(uintptr_t)p0->st[0].code ^ ((uint64_t)p0->serial << 44), p1 ? (uint64_t)(uintptr_t)p1->st[1].code ^ ((uint64_t)p1->serial << 44) : 0, s->sig_tag, tclass[prim] | (uint64_t)s->logic << 8 | (uint64_t)(p1 ? p1->sample_shading & 1 : 0) << 16,
                     (uint64_t)s->ints << 32 | s->sints, (uint64_t)R.tex_int[0] << 32 | R.tex_int[1]};
    uint64_t tag = fnv(0xcbf29ce484222325ULL, w, sizeof w) | 1;
    unsigned slot = (unsigned)(tag >> 20) & 8191;
    if (g_scan_seen[slot] == tag) return;
    g_scan_seen[slot] = tag;
    uint32_t key0[4] = {s->ints, s->sints, R.tex_int[0], R.tex_sint[0]}, key1[4] = {0, 0, R.tex_int[1], R.tex_sint[1]};
    VStage *vs = p0->st[0].vk, *fs = p1 ? p1->st[1].vk : NULL;
    int fs_made = !p1 || (fs && fs->state == 2 && fs->fo == 0 && key_fits(1, key1, fs->key, fs->dep, fs->tex_units));
    int vs_made = fs_made && vs && vs->state == 2 && key_fits(0, key0, vs->key, vs->dep, vs->tex_units) && vs->fo == (fs && fs->ok ? fs->in_attr & ~(vs->out_attr & ~vs->fo) : 0);
    PKey k = s->sig;
    k.topo_class = tclass[prim]; k.logic = s->logic; k.sshade = p1 ? (uint8_t)p1->sample_shading : 0;
    if (vs_made && fs_made) {
        if (!vs->ok || (fs && !fs->ok)) return;
        k.vs = vs->id; k.fs = fs ? fs->id : 0;
        uint64_t h = fnv(0xcbf29ce484222325ULL, &k, sizeof k);
        EnterCriticalSection(&g_sh_lock);
        Pipe *pf = pipe_find(&k, h);
        if (!pf || pf->state == 0) {               /* not there, or waiting in the background queue: to the front */
            Job *j = calloc(1, sizeof *j);
            j->kind = 1; j->pipe = pf ? pf : pipe_new(&k, vs, fs, h, 0);
            job_push_front(j);
            g_scan_pipes++;
        }
        LeaveCriticalSection(&g_sh_lock);
        return;
    }
    SSrc a, b;
    if (!ssrc_of(&a, p0, 0)) return;
    int has_f = p1 && ssrc_of(&b, p1, 1);
    Job *j = calloc(1, sizeof *j + (size_t)a.code_len + a.cdata_size + 16 + (has_f ? (size_t)b.code_len + b.cdata_size + 16 : 0));
    uint8_t *d = j->data;
    j->kind = 2; j->k = k; memcpy(j->key0, key0, 16); memcpy(j->key1, key1, 16);
    job_copy_src(j, &d, 0, &a);
    if (has_f) job_copy_src(j, &d, 1, &b);
    EnterCriticalSection(&g_sh_lock);
    job_push_front(j);
    g_scan_jobs++;
    LeaveCriticalSection(&g_sh_lock);
}
static void scan_list(uint64_t handle, int depth, Scan *s) {
    size_t len = 0;
    uint8_t *data = nvn_front_list(handle, &len);
    if (!data) return;
    for (size_t off = 0; off + sizeof(Cmd) <= len;) {
        const Cmd *m = (const Cmd *)(data + off);
        const uint64_t *a = m->a;
        if (m->size < sizeof(Cmd)) break;
        switch (m->op) {
        case OP_PROGRAM: for (int st = 0; st < 2; st++) if (a[1] & (1u << st)) { Prog *p = P(a[0]); s->prog[st] = p && !p->dead && p->st[st].state ? p : NULL; } break;
        case OP_TARGETS: {
            const TargetRef *col = (const TargetRef *)BLOB(m), *dep = col + 8;
            int n = (int)a[0] < 8 ? (int)a[0] : 8;
            memset(s->col, 0, sizeof s->col); memset(&s->depth, 0, sizeof s->depth); s->ncol = 0;
            for (int i = 0; i < n; i++) if (col[i].tex && !col[i].tex->dead) { s->col[i] = col[i]; s->ncol = i + 1; }
            if (dep->tex && !dep->tex->dead) s->depth = *dep;
            scan_sig(s);
            break;
        }
        case OP_VATTR: s->nattr = (int)a[0] < 32 ? (int)a[0] : 32; memcpy(s->vattr, BLOB(m), (size_t)s->nattr * 4); s->attr_new = 1; break;
        case OP_COLOR: s->logic = ((const uint8_t *)&a[0])[1]; break;
        case OP_DRAW_ARRAYS: case OP_DRAW_ELEMENTS: scan_draw(s, (unsigned)a[0]); break;
        case OP_CALL: for (int i = 0; i < (int)a[0]; i++) { uint64_t h; memcpy(&h, BLOB(m) + i * 8, 8); if (depth < 8) scan_list(h, depth + 1, s); } break;
        default: break;
        }
        off += m->size;
    }
}
static void prewarm_wait(void) {                   /* render thread, before its first batch */
    if (g_pw_waited) return;
    g_pw_waited = 1;
    LARGE_INTEGER fq; QueryPerformanceFrequency(&fq);
    LONG64 t0 = tk();
    WaitForSingleObject(g_pw_gate, INFINITE);
    printf("nvn_vk: pipelines made ahead: %lld of %d listed (%lld stages from their records, %lld entries without their stage files) in %.0f ms on %d threads; the first batch waited %.0f ms for them\n",
           (long long)g_pw_pipes, g_pw_n, (long long)g_pw_stages, (long long)g_pw_failed, (double)(g_pw_t1 - g_pw_t0) * 1000.0 / (double)fq.QuadPart, g_pw_nthread, (double)(tk() - t0) * 1000.0 / (double)fq.QuadPart);
    fflush(stdout);
    free(g_pw_rec); g_pw_rec = NULL;
}
static void m4_report(void) {
    LARGE_INTEGER fq; QueryPerformanceFrequency(&fq);
    for (int i = 0; i < g_rtlog_n; i++) printf("nvn_vk_rt: %d x %d (mip level %d), %d colour targets (first format 0x%x), depth format 0x%x: %lld passes, %lld of them in fight frames, first in frame %lld\n", g_rtlog[i].w, g_rtlog[i].h, g_rtlog[i].lv, g_rtlog[i].ncol, g_rtlog[i].cf, g_rtlog[i].df, g_rtlog[i].n, g_rtlog[i].fight, g_rtlog[i].first);
    double k = 1000.0 / (double)fq.QuadPart;
    LONG64 n = 0, t = 0;
    for (int i = 0; i < H_N; i++) { n += g_hold_n[i]; t += g_hold_tk[i]; }
    printf("nvn_vk: texture descriptor sets: %lld reused after a full comparison of their lists, %lld hash hits with a different list (given a set of their own); samplers given a dummy because the texture is of another kind than the shader declares: %lld\n", (long long)R.sets_reused, (long long)R.tset_collisions, (long long)R.dummy_kind);
    printf("nvn_vk_m4: holds of the render thread at a draw: %lld, %.0f ms in all, longest %.1f ms (stage made at the draw %lld / %.0f ms, stage waited for %lld / %.0f ms, pipeline made at the draw %lld / %.0f ms, pipeline waited for %lld / %.0f ms)\n",
           (long long)n, (double)t * k, (double)g_hold_max * k, (long long)g_hold_n[0], (double)g_hold_tk[0] * k, (long long)g_hold_n[1], (double)g_hold_tk[1] * k, (long long)g_hold_n[2], (double)g_hold_tk[2] * k, (long long)g_hold_n[3], (double)g_hold_tk[3] * k);
    printf("nvn_vk_m4: workers: %lld programs handed over, %lld stages made by them, %lld pipelines made by them; look-ahead: %lld pipelines and %lld draws with stages still to make sent ahead, %.0f ms of reading in all; blind prediction: %lld keys, %lld used; pass signatures %d; nvnProgramSetShaders held its caller %lld times, %.0f ms in all\n",
           (long long)g_w_progs, (long long)g_w_stages, (long long)g_w_pipes, (long long)g_scan_pipes, (long long)g_scan_jobs, (double)g_tm[9] * k, (long long)g_pred_made, (long long)g_pred_used, g_nsig, (long long)g_set_held, (double)g_set_held_tk * k);
    printf("nvn_vk_cscan: container scan %s: %lld containers scanned (%d known), %lld variations, %lld handed to the workers (%lld KB of code copied), %lld pairs found, %.0f ms of the guest threads' time; pipelines made for a container's pass signatures: %lld (counted in the keys above), background jobs %lld queued / %lld done\n",
           g_cscan ? "on" : "off (SSBU_VK_CSCAN=0)", (long long)g_cs_scans, g_ncont, (long long)g_cs_vars, (long long)g_cs_jobs, (long long)(g_cs_bytes >> 10), (long long)g_cs_pairs, (double)g_cs_tk * k, (long long)g_cs_pred, (long long)g_bq_queued, (long long)g_bq_done);
}
static void m4_stop(void) {
    if (!g_pw_nthread) return;
    prewarm_wait();
    EnterCriticalSection(&g_sh_lock);
    g_m4_on = 0; g_m4_quit = 1;
    WakeAllConditionVariable(&g_jq_cv);
    LeaveCriticalSection(&g_sh_lock);
    WaitForMultipleObjects((DWORD)g_pw_nthread, g_pw_thread, TRUE, 60000);
    for (int i = 0; i < g_pw_nthread; i++) CloseHandle(g_pw_thread[i]);
    g_pw_nthread = 0;
    m4_report();
}
static void pcache_save(void) {
    size_t n = 0;
    if (!g_pcache || vkGetPipelineCacheData(V.device, g_pcache, &n, NULL) != VK_SUCCESS || !n) return;
    void *data = malloc(n);
    if (data && vkGetPipelineCacheData(V.device, g_pcache, &n, data) == VK_SUCCESS) {
        char tmp[176];
        snprintf(tmp, sizeof tmp, "%s.tmp", g_pcache_path);
        FILE *fp = fopen(tmp, "wb");
        if (fp) { fwrite(data, 1, n, fp); fclose(fp); MoveFileExA(tmp, g_pcache_path, MOVEFILE_REPLACE_EXISTING); printf("nvn_vk: pipeline cache saved: %llu KB\n", (unsigned long long)(n >> 10)); }
    }
    free(data);
}

/* ---------------------------------------------------------------- session 6: the shader container scan
 * The game keeps its Maxwell stages in "BNSH" containers (a file of their own, or embedded in an effect / shader-database
 * file) and creates a program from a variation only when something first draws with it: FUN_71000382a0 (13.0.4) takes the
 * six stage-code pointers of one variation's program and calls nvnProgramInitialize / nvnProgramSetShaders; its caller
 * FUN_710009c9e0 sets a container up either eagerly (every variation at once) or lazily (flag bit 0).
 * Layout, read from that code and checked against the memory of the running game (SSBU_VK_CSCAN_LOG=1 prints it):
 *   file header: "BNSH", byte-order mark 0xFEFF at +0x0C, offset of the file name at +0x10, offset of the first block at
 *                +0x16 (u16), file size at +0x1C;
 *   block "grsc": variation count at +0x1C (s32), pointer to the variation array at +0x20;
 *   variation (0x40 bytes): three program pointers (source / intermediate / binary) at the offsets the table the game keeps
 *                at *0x71052a32d8 names; a program holds its six stage-code pointers at the offsets of the table 0x7104470aa8;
 *   stage code: among its first words a pointer to the control section (magic 0x98761234) and one to the code section
 *                (magic 0x12345678), the two blocks nvnProgramSetShaders is given.
 * The pointers are absolute once the game has relocated the file; before that they are offsets from the file start: both
 * are accepted. The scan runs on the GUEST thread that hands over the first program of a container not seen before: every
 * variation becomes a background job (stages translated -> SPIR-V -> modules, as for a program handed over), and every
 * pair found gets the pipelines of the pass signatures other pairs of the SAME container were drawn with (now or in
 * earlier runs: pipes.bin), so a container's unseen variations are ready before the game first draws with them. */
typedef struct { uint64_t base, size, id; uint8_t head[32]; int nvar; uint64_t sigs; } Cont;
static Cont g_cont[1024];
static uint64_t g_cont_neg[1024];
static uint32_t g32(uint64_t a) { uint32_t v; memcpy(&v, (const void *)(uintptr_t)a, 4); return v; }
static uint64_t g64(uint64_t a) { uint64_t v; memcpy(&v, (const void *)(uintptr_t)a, 8); return v; }
static void cont_predict(PairRec *pr, int i) {     /* g_sh_lock held */
    if (pr->sigs >> i & 1) return;
    pr->sigs |= 1ull << i;
    PKey k = g_sig[i].k;
    k.vs = pr->vs->id; k.fs = pr->fs ? pr->fs->id : 0; k.sshade = pr->fs ? pr->sshade : 0;
    uint64_t h = fnv(0xcbf29ce484222325ULL, &k, sizeof k);
    if (pipe_find(&k, h)) return;
    Job *j = calloc(1, sizeof *j);
    j->kind = 1; j->pipe = pipe_new(&k, pr->vs, pr->fs, h, 0); j->pipe->predicted = 1;
    g_pred_made++; g_cs_pred++;
    job_push_bg(j);
}
static void cont_learn(PairRec *pr) {              /* g_sh_lock held: a pair of a container was drawn, or was just found by the scan */
    if (!pr->cont || !g_cpredict) return;
    Cont *c = &g_cont[pr->cont - 1];
    uint64_t fresh = pr->used & ~c->sigs;
    if (fresh) {
        c->sigs |= fresh;
        for (PairRec *q = g_pair_all; q; q = q->all) if (q->cont == pr->cont) for (int i = 0; i < g_nsig; i++) if (fresh >> i & 1) cont_predict(q, i);
    }
    for (int i = 0; i < g_nsig; i++) if (c->sigs >> i & 1) cont_predict(pr, i);
}
/* The container around a control section: the nearest "BNSH" header below it whose file size reaches it; 0 when none. */
static uint64_t cont_find(uint64_t control, uint64_t *size) {
    uint64_t step = g_cscan_step, a = control & ~(step - 1), stop = control > (g_cscan_reach << 20) ? control - (g_cscan_reach << 20) : 0x10000;
    if ((control >> 28) == 0x710) return 0;        /* inside the game's own image (0x7100000000 + 256 MB): a program built into the exe, no container; the image is thousands of small regions for VirtualQuery (40 ms a search, measured) */
    for (int regions = 0; a >= stop && regions < 256; regions++) {
        MEMORY_BASIC_INFORMATION mi;
        if (!VirtualQuery((const void *)(uintptr_t)a, &mi, sizeof mi) || mi.State != MEM_COMMIT || (mi.Protect & (PAGE_NOACCESS | PAGE_GUARD))) return 0;
        uint64_t lo = (uint64_t)(uintptr_t)mi.BaseAddress;
        if (lo < stop) lo = stop;
        for (; a >= lo; a -= step)
            if (g32(a) == 0x48534E42u && (g32(a + 0xC) & 0xffff) == 0xFEFFu) {
                uint64_t sz = g32(a + 0x1C);
                if (sz < 0x60 || control >= a + sz) return 0;
                *size = sz;
                return a;
            }
    }
    return 0;
}
static int cont_stage(uint64_t control, uint64_t data, SSrc *o) {      /* as nvnProgramSetShaders reads a stage (nvn_gl.c prog_set_shaders): 0 vertex, 1 fragment, 2 compute, -1 none, -2 a stage this back end does not take */
    static const int8_t stage_of_type[16] = {-1, 0, 3, 4, 2, 1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1};
    uint32_t ctl[8];
    memset(o, 0, sizeof *o);
    int len = (int)g32(control + 0x6f8);
    if (len <= 0 || len > (4 << 20)) return -1;
    memcpy(ctl, (const void *)(uintptr_t)(control + 0x6f0), 32);
    if (g32(control + 0x714) == 5) {
        o->stage = 5; o->code = (const uint8_t *)(uintptr_t)data; o->code_len = len;
        for (int k = 0; k < 3; k++) o->local[k] = g32(control + 0x748 + (uint64_t)k * 4);
        o->smem = g32(control + 0x754); o->lmem = g32(control + 0x758);
        if (ctl[3] && ctl[4]) { o->cdata = o->code + ctl[4]; o->cdata_size = ctl[3]; }
        return 2;
    }
    if (g32(data) != 0x12345678u) return -1;
    int s = stage_of_type[(g32(data + 0x30) >> 10) & 15];
    if (s < 0) return -1;
    if (s > 1) return -2;
    o->stage = s; o->code = (const uint8_t *)(uintptr_t)(data + 0x30); o->code_len = len;
    if (ctl[3] && ctl[4]) { o->cdata = o->code - 0x30 + ctl[4]; o->cdata_size = ctl[3]; }
    return s;
}
/* Walks the container at base (size bytes, all readable): one background job per variation. Returns the variation count;
 * `tag` = 1 + the container's index, for the pairs. */
static int cont_walk(uint64_t base, uint64_t size, int tag, int *njobs) {
    uint64_t end = base + size, blk = base + (g32(base + 0x14) >> 16), voff[3] = {0, 8, 0x10}, soff[6] = {8, 0x10, 0x18, 0x20, 0x28, 0x30};
    *njobs = 0;
    if (blk + 0x28 > end || g32(blk) != 0x63737267u) return -1;      /* "grsc" */
    int nvar = (int)g32(blk + 0x1C);
    uint64_t vars = g64(blk + 0x20);
    if (vars < size) vars += base;                 /* not relocated yet */
    if (nvar <= 0 || nvar > 200000 || vars < base || vars + (uint64_t)nvar * 0x40 > end) return -1;
    if (g_game_tables) {                           /* the game's own offset tables (13.0.4); the defaults above are what they held when read */
        uint64_t t = g64(0x71052a32d8ull);
        for (int i = 0; i < 3 && t; i++) { uint64_t v = g64(t + (uint64_t)i * 8); if (v < 0x40) voff[i] = v; }
        for (int i = 0; i < 6; i++) { uint64_t v = g64(0x7104470aa8ull + (uint64_t)i * 8); if (v && v < 0x70) soff[i] = v; }
    }
    for (int v = 0; v < nvar; v++) {
        SSrc s[3];
        int has[3] = {0, 0, 0}, bad = 0;
        for (int pi = 2; pi >= 0 && !has[0] && !has[2]; pi--) {      /* binary program first */
            uint64_t prog = g64(vars + (uint64_t)v * 0x40 + voff[pi]);
            if (prog && prog < size) prog += base;
            if (prog < base || prog + 0x70 > end) continue;
            for (int st = 0; st < 6; st++) {
                uint64_t code = g64(prog + soff[st]), control = 0, data = 0;
                if (code && code < size) code += base;
                if (code < base || code + 0x40 > end) continue;
                /* stage code: {u64 GPU address (the game fills it), control pointer, code pointer, u32 code size, u32 control size} */
                control = g64(code + 8); data = g64(code + 16);
                if (control && control < size) control += base;
                if (data && data < size) data += base;
                if (control < base || control + 0x760 > end || g32(control) != 0x98761234u) control = 0;
                if (data < base || data + 0x40 > end) data = 0;
                if (g_cscan_log && v == 0) { printf("nvn_vk_cscan:   variation 0 program %d stage slot %d: code struct at +%llx: %016llx %016llx %016llx %016llx | control +%llx, data +%llx\n", pi, st, (unsigned long long)(code - base),
                                                    (unsigned long long)g64(code), (unsigned long long)g64(code + 8), (unsigned long long)g64(code + 16), (unsigned long long)g64(code + 24), (unsigned long long)(control ? control - base : 0), (unsigned long long)(data ? data - base : 0)); }
                if (!control || !data) continue;
                SSrc one;
                int k = cont_stage(control, data, &one);
                if (k == -2) bad = 1;
                if (k < 0) continue;
                if ((uint64_t)(uintptr_t)one.code + (uint64_t)one.code_len > end || (one.cdata && ((uint64_t)(uintptr_t)one.cdata < base || (uint64_t)(uintptr_t)one.cdata + one.cdata_size > end))) continue;
                one.serial = -(v + 1);
                s[k] = one; has[k] = 1;
            }
        }
        if (bad || (!has[0] && !has[2])) continue;
        size_t need = 0;
        for (int i = 0; i < 3; i++) if (has[i]) need += (size_t)s[i].code_len + s[i].cdata_size + 16;
        Job *j = calloc(1, sizeof *j + need);
        uint8_t *d = j->data;
        j->cont = tag;
        for (int i = 0; i < 3; i++) if (has[i]) job_copy_src(j, &d, i, &s[i]);
        InterlockedAdd64(&g_cs_bytes, (LONG64)need);
        EnterCriticalSection(&g_sh_lock);
        job_push_bg(j);
        LeaveCriticalSection(&g_sh_lock);
        (*njobs)++;
    }
    return nvar;
}
/* GUEST thread, nvnProgramSetShaders (front end), once per stage handed over: `control` = the guest address of its control
 * section. A container not met before is scanned whole. */
void nvn_vk_container_seen(uint64_t control, uint64_t prog) {
    if (!g_cscan || !g_m4_on || !control || !prog) return;
    if (g_cscan_log) { static LONG nl; if (InterlockedIncrement(&nl) <= 6) { printf("nvn_vk_cscan: control %llx, variation program %llx:", (unsigned long long)control, (unsigned long long)prog); for (int i = 0; i < 16; i++) printf(" %llx", (unsigned long long)g64(prog + (uint64_t)i * 8)); printf("\n"); } }
    control = prog;                                /* the address the container is looked for around */
    unsigned ns = (unsigned)((control * 0x9E3779B97F4A7C15ull) >> 54);
    EnterCriticalSection(&g_sh_lock);
    for (int i = 0; i < g_ncont; i++) if (control - g_cont[i].base < g_cont[i].size) {
        if (!memcmp(g_cont[i].head, (const void *)(uintptr_t)g_cont[i].base, 32)) { LeaveCriticalSection(&g_sh_lock); return; }
        g_cont[i].size = 0;                        /* the memory holds something else now */
    }
    if (g_cont_neg[ns] == control) { LeaveCriticalSection(&g_sh_lock); return; }
    LeaveCriticalSection(&g_sh_lock);
    LONG64 t0 = tk();
    uint64_t size = 0, base = cont_find(control, &size);
    if (g_cscan_log && (control >> 28) != 0x710) { static LONG nl; if (InterlockedIncrement(&nl) <= 40) { LARGE_INTEGER fq; QueryPerformanceFrequency(&fq); printf("nvn_vk_cscan: control %llx -> container %llx (%llu KB), %.1f ms\n", (unsigned long long)control, (unsigned long long)base, (unsigned long long)(size >> 10), (double)(tk() - t0) * 1000.0 / (double)fq.QuadPart); fflush(stdout); } }
    if (!base) { g_cont_neg[ns] = control; InterlockedAdd64(&g_cs_tk, tk() - t0); return; }
    uint64_t id = fnv(0xcbf29ce484222325ULL, (const void *)(uintptr_t)base, 32);
    {   uint32_t no = g32(base + 0x10);            /* the file name */
        if (no && no + 2 < size) id = fnv(id, (const void *)(uintptr_t)(base + no), strnlen((const char *)(uintptr_t)(base + no), (size_t)(size - no) < 96 ? (size_t)(size - no) : 96)); }
    int idx = -1, known = 0;
    EnterCriticalSection(&g_sh_lock);
    for (int i = 0; i < g_ncont; i++) if (g_cont[i].id == id) { idx = i; known = g_cont[i].size != 0 || g_cont[i].nvar > 0; if (g_cont[i].base == base && g_cont[i].size) { LeaveCriticalSection(&g_sh_lock); return; } }
    if (idx < 0 && g_ncont < 1024) { idx = g_ncont++; memset(&g_cont[idx], 0, sizeof g_cont[idx]); g_cont[idx].id = id; }
    if (idx >= 0) { g_cont[idx].base = base; g_cont[idx].size = size; memcpy(g_cont[idx].head, (const void *)(uintptr_t)base, 32); }
    LeaveCriticalSection(&g_sh_lock);
    if (idx < 0 || known) return;                  /* the same file loaded again at another address: its pairs are known */
    int njobs = 0, nvar = cont_walk(base, size, idx + 1, &njobs);
    g_cont[idx].nvar = nvar > 0 ? nvar : 1;
    InterlockedIncrement64(&g_cs_scans); InterlockedAdd64(&g_cs_vars, nvar > 0 ? nvar : 0); InterlockedAdd64(&g_cs_jobs, njobs); InterlockedAdd64(&g_cs_tk, tk() - t0);
    if (g_cscan_log || nvar < 0) {
        uint32_t no = g32(base + 0x10);
        char name[64] = "";
        if (no && no + 2 < size) snprintf(name, sizeof name, "%.60s", (const char *)(uintptr_t)(base + no));
        printf("nvn_vk_cscan: container #%d \"%s\" at %llx, %llu KB, %d variations, %d queued (frame %lld, %s)%s\n", idx, name, (unsigned long long)base, (unsigned long long)(size >> 10), nvar, njobs, nvn_front_frame_next(),
               g_in_fight ? "IN A FIGHT" : "no fight", nvar < 0 ? ": NOT UNDERSTOOD (no grsc block or variation array out of the file)" : "");
        fflush(stdout);
    }
}
/* `ssbu_vk1.exe --prepare-shaders [folder]` (boot.c): no game, no window, no Vulkan device. Every *.bnsh file of the folder
 * (tools_vk/bnsh_extract.py writes them from data.arc) is walked as the scan above walks a container in the game's memory
 * (file offsets instead of pointers) and its stages are translated on the workers: ..\cache\vk\stage and \spv are then
 * what a run finds when the game loads the container. Pipelines are NOT made here: they need the GPU and the pass a pair
 * is drawn in, which only a run knows (pipes.bin). */
int nvn_vk_prepare_shaders(const char *dir) {
    char pat[300], path[400];
    WIN32_FIND_DATAA fd;
    LARGE_INTEGER fq; QueryPerformanceFrequency(&fq);
    LONG64 t0 = tk(), last = t0;
    int files = 0, bad = 0;
    long long vars = 0, jobs = 0;
    if (!dir) dir = "../cache/vk_containers";
    g_offline = 1; g_game_tables = 0; g_cpredict = 0;
    InitializeCriticalSection(&g_sh_lock);
    InitializeConditionVariable(&g_sh_cv); InitializeConditionVariable(&g_jq_cv);
    CreateDirectoryA("../cache", NULL); CreateDirectoryA("../cache/vk", NULL); CreateDirectoryA("../cache/vk/spv", NULL); CreateDirectoryA("../cache/vk/stage", NULL);
    {   HMODULE m = LoadLibraryA("ssbu_glslang.dll");
        g_glsl_to_spirv = m ? (void *)GetProcAddress(m, "ssbu_glsl_to_spirv") : NULL; g_spirv_free = m ? (void *)GetProcAddress(m, "ssbu_spirv_free") : NULL;
        if (!g_glsl_to_spirv || !g_spirv_free) { printf("prepare-shaders: ssbu_glslang.dll cannot be loaded (build_glslang.bat makes it)\n"); return 2; }
    }
    SYSTEM_INFO si;
    GetSystemInfo(&si);
    g_pw_nthread = (int)si.dwNumberOfProcessors > 16 ? 16 : (int)si.dwNumberOfProcessors;
    g_pw_gate = CreateEventA(NULL, TRUE, FALSE, NULL);
    g_pw_left = g_pw_nthread;
    for (int i = 0; i < g_pw_nthread; i++) g_pw_thread[i] = CreateThread(NULL, 0, pw_main, NULL, 0, NULL);
    snprintf(pat, sizeof pat, "%s/*.bnsh", dir);
    HANDLE h = FindFirstFileA(pat, &fd);
    if (h == INVALID_HANDLE_VALUE) { printf("prepare-shaders: no *.bnsh file in %s (run: python tools_vk/bnsh_extract.py)\n", dir); return 2; }
    do {
        snprintf(path, sizeof path, "%s/%s", dir, fd.cFileName);
        FILE *fp = fopen(path, "rb");
        if (!fp) continue;
        fseek(fp, 0, SEEK_END); long n = ftell(fp); fseek(fp, 0, SEEK_SET);
        uint8_t *buf = n >= 0x60 ? _aligned_malloc((size_t)n + 64, 4096) : NULL;
        if (buf && fread(buf, 1, (size_t)n, fp) == (size_t)n && g32((uint64_t)(uintptr_t)buf) == 0x48534E42u) {
            int nj = 0, nv = cont_walk((uint64_t)(uintptr_t)buf, (uint64_t)n, 0, &nj);
            if (nv < 0) { bad++; printf("prepare-shaders: %s: not understood (no grsc block, or its variation array lies outside the file)\n", fd.cFileName); }
            else { vars += nv; jobs += nj; }
            files++;
        }
        if (buf) _aligned_free(buf);                /* the jobs hold their own copy of the code */
        fclose(fp);
        if (tk() - last > 2 * fq.QuadPart) { last = tk(); printf("prepare-shaders: %d containers read, %lld variations, %lld of %lld translated (%.0f s)\n", files, vars, (long long)g_bq_done, (long long)g_bq_queued, (double)(last - t0) / (double)fq.QuadPart); }
        EnterCriticalSection(&g_sh_lock);          /* not more than 4,000 copies of code waiting */
        while (g_bq_queued - g_bq_done > 4000) SleepConditionVariableCS(&g_sh_cv, &g_sh_lock, 200);
        LeaveCriticalSection(&g_sh_lock);
    } while (FindNextFileA(h, &fd));
    FindClose(h);
    EnterCriticalSection(&g_sh_lock);
    while (g_bq_done < g_bq_queued) {
        SleepConditionVariableCS(&g_sh_cv, &g_sh_lock, 500);
        if (tk() - last > 2 * fq.QuadPart) { last = tk(); printf("prepare-shaders: %d containers read, %lld variations, %lld of %lld translated (%.0f s)\n", files, vars, (long long)g_bq_done, (long long)g_bq_queued, (double)(last - t0) / (double)fq.QuadPart); }
    }
    g_m4_quit = 1;
    WakeAllConditionVariable(&g_jq_cv);
    LeaveCriticalSection(&g_sh_lock);
    WaitForMultipleObjects((DWORD)g_pw_nthread, g_pw_thread, TRUE, 60000);
    long long made = 0, failed = 0;
    for (int i = 0; i < 4096; i++) for (VStage *v = g_vstage[i]; v; v = v->next) { if (v->ok) made++; else failed++; }
    printf("prepare-shaders: done in %.0f s on %d threads: %d containers (%d not understood), %lld variations, %lld handed to the workers, %lld distinct stage variants ready in ../cache/vk (%lld could not be translated)\n",
           (double)(tk() - t0) / (double)fq.QuadPart, g_pw_nthread, files, bad, vars, jobs, made, failed);
    return bad || failed ? 1 : 0;
}
