"""Track L1: input-to-photon of every injected press from the l1-after lines of a log (SSBU_L1=1).
   python tests/l1_press.py <log> [k=2]   k = presents after the press poll's own present that carry its first picture
   (measured by the differential pictures, tests/l1_shots/fp vs fn: the present call 2 frames after the press poll)."""
import re, sys, statistics
k = int(sys.argv[2]) if len(sys.argv) > 2 else 2
v = []
for line in open(sys.argv[1], errors='replace'):
    m = re.match(r'l1-after: present (\d+) after the press poll.*next vblank ([-+0-9.]+) ms', line)
    if m and int(m.group(1)) == k: v.append(float(m.group(2)))
if v: print('%s: %d presses: press poll -> first vblank that can show its picture: mean %.2f ms (%.2f frames of 16.67), min %.2f, max %.2f' % (sys.argv[1], len(v), statistics.mean(v), statistics.mean(v) / 16.667, min(v), max(v)))
