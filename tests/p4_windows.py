"""P3 round 4: fight windows of a summary against the goal (>= 59.5 fps and p99 <= 25 ms).  python tests/p4_windows.py <summary.txt>..."""
import re, sys
for path in sys.argv[1:]:
    w = []
    for l in open(path, errors='replace'):
        m = re.match(r'\s*frames\s+(\d+)\.\.\s*(\d+)\s+BATTLE avg\s+([\d.]+) ms \(\s*([\d.]+) fps\)\s+median\s+([\d.]+)\s+p99\s+([\d.]+)\s+max\s+([\d.]+)', l)
        if m: w.append((int(m.group(1)), float(m.group(4)), float(m.group(6)), float(m.group(7))))
    ok = [x for x in w if x[1] >= 59.5 and x[2] <= 25.0]
    bad = [x for x in w if x not in ok]
    print('%s: %d windows with compute dispatches, %d at >= 59.5 fps and p99 <= 25 ms; worst window %.1f fps; longest frame %.0f ms; not clean: %s' % (
        path.split('/')[-1], len(w), len(ok), min(x[1] for x in w) if w else 0, max(x[3] for x in w) if w else 0, ' '.join('%d(%.1f fps, p99 %.0f, max %.0f)' % x for x in bad)))
