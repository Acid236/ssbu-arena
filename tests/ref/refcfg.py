"""Paths, constants and the emulator configuration of the reference comparison (plan/phases/T1_reference.md).

The reference emulator is a COPY of the owner's Eden build under Documents/SSBU/ref-emu/eden, in portable mode
(a `user` folder next to the exe), so nothing in Downloads or %APPDATA% is ever written.
`python tests/ref/refcfg.py` (re)writes the configuration file and prints what it set."""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
STUDY = os.path.normpath(os.path.join(HERE, '..', '..'))                    # recomp-study
ROOT = os.path.normpath(os.path.join(STUDY, '..'))                          # Documents/SSBU
EMU_DIR = os.path.join(ROOT, 'ref-emu', 'eden')
EMU_EXE = os.path.join(EMU_DIR, 'eden.exe')
EMU_USER = os.path.join(EMU_DIR, 'user')
EMU_SHOTS = os.path.join(EMU_USER, 'screenshots')
EMU_TAS = os.path.join(EMU_USER, 'tas', 'script0-1.txt')
EMU_SAVE_ROOT = os.path.join(EMU_USER, 'nand', 'user', 'save', '0000000000000000')
TITLE_ID = '01006A800016E000'
GAME = os.path.join(os.path.expanduser('~'), 'Downloads', 'Super Smash Bros Ultimate [NSZ]',
                    'Super Smash Bros Ultimate [01006A800016E000][v0] (13.63 GB).nsp')
OWNER_SAVE = os.path.join(ROOT, 'userdata', 'save', 'save_data')           # read once, never written
SAVE_BASE = os.path.join(ROOT, 'ref-emu', 'save_base')                      # the snapshot BOTH sides start from, every run
PORT_SAVE = os.path.join(SAVE_BASE, 'save', 'save_data')


def ensure_save_base():
    """the snapshot is taken once from the committed save of ..\\userdata; delete nothing, re-snapshot by renaming the folder"""
    import shutil
    if not os.path.isdir(PORT_SAVE):
        os.makedirs(os.path.dirname(PORT_SAVE), exist_ok=True)
        shutil.copytree(OWNER_SAVE, PORT_SAVE)
    return PORT_SAVE
GOLDEN = os.path.join(HERE, 'golden')
OUT = os.path.join(HERE, 'out')
WORK = os.path.join(ROOT, 'ref-emu', 'work')                                # captures of the current runs (large)

DSU_PORT = 26761                       # not the default 26760, so a DSU server of the owner is never talked to
DSU_GUID = '0000000000000000000000007f000001'      # UDPClient::GetHostUUID("127.0.0.1").RawString()

# Switch button -> value of InputCommon::CemuhookUDP::PadButton (udp_client.h)
DSU_BUTTON = {'a': 0x2000, 'b': 0x4000, 'x': 0x1000, 'y': 0x8000, 'lstick': 0x0002, 'rstick': 0x0004, 'l': 0x0400,
              'r': 0x0800, 'zl': 0x0100, 'zr': 0x0200, 'plus': 0x0008, 'minus': 0x0001, 'dleft': 0x0080, 'dup': 0x0010,
              'dright': 0x0020, 'ddown': 0x0040, 'home': 0x40000, 'screenshot': 0x80000}


def config_text():
    """qt-config.ini: only what differs from the emulator's defaults. Every `key=value` needs `key\\default=false`,
    otherwise the frontend ignores the value and uses the default."""
    def udp(extra):
        return '"engine:cemuhookudp,guid:%s,port:%d,pad:0,%s"' % (DSU_GUID, DSU_PORT, extra)
    sec = {'Controls': [], 'Core': [], 'Renderer': [], 'Audio': [], 'System': [], 'UI': [], 'Miscellaneous': [], 'WebService': []}
    c = sec['Controls']
    c += [('enable_udp_controller', 'true'), ('udp_input_servers', '127.0.0.1:%d' % DSU_PORT),
          ('enable_raw_input', 'false'), ('enable_joycon_driver', 'false'), ('enable_procon_driver', 'false'),
          ('vibration_enabled', 'false'), ('motion_enabled', 'false'), ('keyboard_enabled', 'false'), ('mouse_enabled', 'false'),
          ('tas_enable', 'true'), ('tas_loop', 'false'), ('pause_tas_on_load', 'false'), ('tas_show_recording_dialog', 'false'),
          ('controller_navigation', 'false'),
          ('player_0_type', '0'), ('player_0_connected', 'true'), ('player_0_vibration_enabled', 'false')]
    for name, bit in DSU_BUTTON.items():
        c.append(('player_0_button_' + name, udp('button:%d' % bit)))
    for name in ('slleft', 'srleft', 'slright', 'srright'):
        c.append(('player_0_button_' + name, '"engine:keyboard,code:0,toggle:0"'))
    c += [('player_0_lstick', udp('axis_x:0,axis_y:1,deadzone:0.000000,range:1.000000')),
          ('player_0_rstick', udp('axis_x:2,axis_y:3,deadzone:0.000000,range:1.000000')),
          ('player_0_motionleft', '"engine:keyboard,code:0,toggle:0"'), ('player_0_motionright', '"engine:keyboard,code:0,toggle:0"')]
    for p in range(1, 8):
        c.append(('player_%d_connected' % p, 'false'))
    sec['Core'] += [('use_multi_core', 'true'), ('use_speed_limit', 'true'), ('speed_limit', '100')]
    sec['Renderer'] += [('backend', '1'),                 # Vulkan
                        ('resolution_setup', '3'),        # ResolutionSetup::Res1X  -> 1920x1080 docked
                        ('aspect_ratio', '0'), ('anti_aliasing', '0'), ('scaling_filter', '1'), ('fullscreen_mode', '0'),
                        ('use_asynchronous_shaders', 'false'),      # a frame is never shown with draws missing
                        ('use_disk_shader_cache', 'true'), ('max_anisotropy', '0'), ('bg_red', '0'), ('bg_green', '0'), ('bg_blue', '0')]
    sec['Audio'] += [('audio_muted', 'true'), ('volume', '0'), ('muteWhenInBackground', 'false')]
    sec['System'] += [('language_index', '4'),            # Language::Italian (the port reports "it")
                      ('region_index', '2'),              # Europe
                      ('use_docked_mode', '1'), ('rng_seed_enabled', 'true'), ('rng_seed', '0'),
                      ('custom_rtc_enabled', 'true'), ('custom_rtc_offset', '0'), ('current_user', '0')]
    sec['Miscellaneous'] += [('log_filter', '"*:Info"'), ('first_launch', 'false'), ('censor_username', 'true'),
                             ('flush_line', 'true')]         # the log is read while the emulator runs (end of a TAS playback)
    sec['WebService'] += [('eden_username', ''), ('eden_token', '')]
    sec['UI'] += [('firstStart', 'false'), ('singleWindowMode', 'true'), ('fullscreen', 'false'), ('confirmStop', '2'),
                  ('pauseWhenInBackground', 'false'), ('hideInactiveMouse', 'true'), ('disableControllerApplet', 'true'),
                  ('select_user_on_boot', 'false'), ('check_for_updates', 'false'), ('enable_discord_presence', 'false'),
                  ('calloutFlags', '255'), ('showConsole', 'false'),
                  ('Screenshots\\enable_screenshot_save_as', 'false'),      # no file dialog: the frontend names the file itself
                  ('Screenshots\\screenshot_height', '0'),                  # 0 = the emulated output height (1080 docked at 1x)
                  # the controller's Capture button takes the screenshot; nothing else is bound to the controller
                  ('Shortcuts\\Main%20Window\\Capture%20Screenshot\\KeySeq', 'Ctrl+P'),
                  ('Shortcuts\\Main%20Window\\Capture%20Screenshot\\Controller_KeySeq', 'Screenshot'),
                  ('Shortcuts\\Main%20Window\\Capture%20Screenshot\\Context', '3'),
                  ('Shortcuts\\Main%20Window\\Capture%20Screenshot\\Repeat', 'false'),
                  # both stick buttons together (nothing in the game's menus; the Home button suspends the game) start the TAS script user/tas/script0-1.txt (frame-exact stick moves)
                  ('Shortcuts\\Main%20Window\\TAS%20Start\\Stop\\KeySeq', 'Ctrl+F5'),
                  ('Shortcuts\\Main%20Window\\TAS%20Start\\Stop\\Controller_KeySeq', 'Left_Stick+Right_Stick'),
                  ('Shortcuts\\Main%20Window\\TAS%20Start\\Stop\\Context', '2'),
                  ('Shortcuts\\Main%20Window\\TAS%20Start\\Stop\\Repeat', 'false')]
    # add-on content off: the port reports no add-on content, and with it the game shows "... joins the battle!"
    # notices after the title and a larger roster. Same switch as Properties > Add-Ons > DLC in the frontend.
    out = ['[DisabledAddOns]', 'size=1', '1\\title_id\\default=false', '1\\title_id=%d' % int(TITLE_ID, 16),
           '1\\disabled\\size=1', '1\\disabled\\1\\d\\default=false', '1\\disabled\\1\\d=DLC', '']
    for name, items in sec.items():
        out.append('[%s]' % name)
        for k, v in items:
            out.append('%s\\default=false' % k)
            out.append('%s=%s' % (k, v))
        out.append('')
    return '\n'.join(out) + '\n'


def write_config():
    d = os.path.join(EMU_USER, 'config')
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, 'qt-config.ini')
    with open(path, 'w', newline='\n') as f:
        f.write(config_text())
    for sub in ('screenshots', 'log', 'tas'):
        os.makedirs(os.path.join(EMU_USER, sub), exist_ok=True)
    return path


if __name__ == '__main__':
    print('wrote', write_config())
    print(config_text())
