#version 450
// U1, the settings menu (nvn_vk_menu.c). Compiled into menu_spv.h with glslang (see that file).
layout(set = 0, binding = 0) uniform sampler2D u_tex;
layout(location = 0) in vec4 v_col;
layout(location = 1) in vec2 v_uv;
layout(location = 0) out vec4 o_col;
void main() { o_col = v_col * texture(u_tex, v_uv); }
