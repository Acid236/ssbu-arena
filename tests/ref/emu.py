"""Start / drive / stop the reference emulator (the copy under Documents/SSBU/ref-emu, portable mode).

Input goes through the DSU server (dsu.py). Frames come from the emulator's own screenshot function, triggered by the
controller's Capture button: a PNG of the emulated output (1920x1080 docked at 1x), independent of the window's size,
position or visibility. The window is started minimised and is never activated; no key or mouse event is sent.
Only the process started here is ever closed or killed."""
import glob, os, shutil, subprocess, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import refcfg
from dsu import DsuPad


def prepare_save(mode, log=print):
    """Save data of the emulated user before a run.
       port  = a copy of the save snapshot ref-emu/save_base (the same one the port run gets), so both sides start equal
       fresh = no save data (the game creates one)
       keep  = whatever the last reference run left
    Nothing is deleted: the previous save is moved to ref-emu/trash/<time>/."""
    if mode == 'keep':
        return
    refcfg.ensure_save_base()
    users = [d for d in glob.glob(os.path.join(refcfg.EMU_SAVE_ROOT, '*')) if os.path.isdir(os.path.join(d, refcfg.TITLE_ID, 'save_data'))]
    stamp = time.strftime('%Y%m%d_%H%M%S')
    for i, u in enumerate(users):
        src = os.path.join(u, refcfg.TITLE_ID, 'save_data')
        dst = os.path.join(refcfg.ROOT, 'ref-emu', 'trash', stamp, str(i), 'save_data')
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.move(src, dst)
        log('save: previous emulator save moved to', dst)
        if mode == 'port':
            shutil.copytree(refcfg.PORT_SAVE, src)
            log('save: copied the port save', refcfg.PORT_SAVE, '->', src)
    if mode == 'port' and not users:
        log('save: the emulator has no user save folder yet (first run): starting fresh; run again for a copy of the port save')


class Emulator:
    def __init__(self, log=print):
        self.proc = None
        self.pad = None
        self.show = 'min'
        self.log = log
        self.t0 = time.time()

    def say(self, *a):
        self.log('[emu %6.1f s]' % (time.time() - self.t0), *a)

    def start(self, show='min'):
        if not os.path.isfile(refcfg.EMU_EXE):
            raise SystemExit('no emulator copy at %s (see plan/phases/T1_reference.md, "Setting up the copy")' % refcfg.EMU_EXE)
        if not os.path.isdir(refcfg.EMU_USER):
            raise SystemExit('no portable user folder at %s: refusing to start (the emulator would use %%APPDATA%%)' % refcfg.EMU_USER)
        refcfg.write_config()
        self.pad = DsuPad(refcfg.DSU_PORT)
        self.pad.start()
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = {'min': 7, 'normal': 4}[show]          # SW_SHOWMINNOACTIVE / SW_SHOWNOACTIVATE
        self.show = show
        self.t0 = time.time()
        self.proc = subprocess.Popen([refcfg.EMU_EXE, '-g', refcfg.GAME], cwd=refcfg.EMU_DIR, startupinfo=si,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.say('started pid', self.proc.pid)
        return self

    def alive(self):
        return self.proc is not None and self.proc.poll() is None

    def wait_pad(self, timeout=60):
        end = time.time() + timeout
        while time.time() < end and self.alive():
            if self.pad.connected():
                self.say('emulator is reading the DSU pad')
                return True
            time.sleep(0.2)
        return False

    def windows(self):
        import win32gui, win32process
        out = []
        def each(h, _):
            try:
                _, pid = win32process.GetWindowThreadProcessId(h)
            except Exception:
                return True
            if pid == self.proc.pid and win32gui.IsWindowVisible(h):
                out.append((h, win32gui.GetWindowText(h), win32gui.GetClassName(h), win32gui.GetWindowRect(h)))
            return True
        win32gui.EnumWindows(each, None)
        return out

    def keep_minimised(self):
        """the emulator's window stays minimised and is never activated (no input is sent to it)"""
        try:
            import win32gui
            for h, title, cls, _ in self.windows():
                if 'Eden' in title and not win32gui.IsIconic(h):
                    win32gui.ShowWindow(h, 7)             # SW_SHOWMINNOACTIVE
        except Exception:
            pass

    def screenshot(self, dest=None, timeout=8.0, attempts=15):
        """press Capture, wait for the PNG the emulator writes, return its path (moved to dest if given)"""
        before = set(glob.glob(os.path.join(refcfg.EMU_SHOTS, '*.png')))
        for attempt in range(attempts):
            if self.show == 'min':
                self.keep_minimised()
            self.pad.capture()
            end = time.time() + timeout
            while time.time() < end:
                new = [p for p in glob.glob(os.path.join(refcfg.EMU_SHOTS, '*.png')) if p not in before]
                if new:
                    p = max(new, key=os.path.getmtime)
                    for _ in range(160):                      # wait until the file is complete: a PNG ends with IEND
                        try:
                            with open(p, 'rb') as f:
                                f.seek(0, 2)
                                if f.tell() >= 64:
                                    f.seek(-12, 2)
                                    if b'IEND' in f.read(12):
                                        break
                        except OSError:
                            pass
                        time.sleep(0.05)
                    if dest:
                        os.makedirs(os.path.dirname(dest), exist_ok=True)
                        for _ in range(60):                   # the emulator may still hold the file open
                            try:
                                shutil.move(p, dest)
                                break
                            except OSError:
                                time.sleep(0.05)
                        return dest
                    return p
                if not self.alive():
                    raise RuntimeError('emulator exited')
                time.sleep(0.05)
            self.say('no screenshot appeared, attempt', attempt + 1)
        return None

    def stop(self):
        if self.proc and self.alive():
            try:
                import win32gui, win32con
                for h, title, cls, _ in self.windows():
                    if 'Eden' in title or 'eden' in title:
                        win32gui.PostMessage(h, win32con.WM_CLOSE, 0, 0)
                self.proc.wait(12)
            except Exception:
                pass
            if self.alive():
                self.proc.terminate()
                try:
                    self.proc.wait(10)
                except Exception:
                    pass
            self.say('stopped')
        if self.pad:
            self.pad.stop()


if __name__ == '__main__':
    # smoke test: boot, list windows, take a screenshot every few seconds.   python tests/ref/emu.py [seconds] [show]
    secs = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    e = Emulator().start(sys.argv[2] if len(sys.argv) > 2 else 'min')
    try:
        print('pad connected:', e.wait_pad())
        out = os.path.join(refcfg.WORK, 'smoke')
        n = 0
        while time.time() - e.t0 < secs and e.alive():
            time.sleep(5)
            if n == 0:
                for w in e.windows():
                    print('window', w)
            p = e.screenshot(os.path.join(out, 'smoke_%03d.png' % n))
            e.say('screenshot', p)
            n += 1
    finally:
        e.stop()
