/* Track S test exe only (fighter_sdk/tools/link_exe.py): on 2026-10-09 nvn_gl.c (track V, in progress) referred to
 * rb_vk, which is to live in nvn_vk_draw.c - a file that did not exist yet, so no exe linked. This empty back-end
 * table lets the OpenGL build link; it is never used unless the Vulkan renderer is selected. Delete this file and
 * its mention in link_exe.py once nvn_vk_draw.c exists. */
#include "../nvn_front.h"
const RBackend rb_vk = {0};
