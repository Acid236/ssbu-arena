#version 450
// U1, the settings menu (nvn_vk_menu.c): Dear ImGui's vertices. Compiled into menu_spv.h with glslang (see that file).
layout(location = 0) in vec2 a_pos;
layout(location = 1) in vec2 a_uv;
layout(location = 2) in vec4 a_col;
layout(push_constant) uniform PC { vec2 scale; vec2 translate; float srgb; } pc;
layout(location = 0) out vec4 v_col;
layout(location = 1) out vec2 v_uv;
void main() {
    vec4 c = a_col;
    if (pc.srgb > 0.5) c.rgb = pow(c.rgb, vec3(2.2));   // an SRGB swapchain converts back on write: the colours stay as ImGui meant them
    v_col = c;
    v_uv = a_uv;
    gl_Position = vec4(a_pos * pc.scale + pc.translate, 0.0, 1.0);
}
