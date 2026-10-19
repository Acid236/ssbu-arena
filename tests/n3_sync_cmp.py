#!/usr/bin/env python3
"""Compare per-frame fight-state hashes of two online-match instances and summarise their logs.

Usage: python tests\\n3_sync_cmp.py <tagA> <tagB>
Reads tests/logs/n11_<tag>.hash.txt and tests/logs/n11_<tag>.log (relative to this script).
Standard library only.
"""

import os
import sys

LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
MIN_SYNC_FRAMES = 600
MAX_LOG_LINES = 30
LINE_CLIP = 200
DEBUG_PATTERNS = ["debug match: fight", "debug end", "GUEST TRAP", "HOST EXCEPTION", "terminate"]


def clip(s):
    s = s.rstrip("\r\n")
    return s if len(s) <= LINE_CLIP else s[:LINE_CLIP] + "..."


def read_lines(path):
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read().splitlines()


def parse_hash_line(line):
    """Return a record for a complete 'F ' line, or None.

    The compared key is the token list up to (not including) the 'H' token,
    capped at 20 tokens. That is: F n e i st s mot m mf f x x y y dmg d rngcalls r rng g.
    """
    if not line.startswith("F "):
        return None
    tokens = line.split()
    if len(tokens) < 20:
        return None
    key = []
    for tok in tokens[:20]:
        if tok == "H":
            break
        key.append(tok)
    if len(key) < 20:
        return None
    # key[0] = 'F', key[1] = frame, then name/value pairs starting at index 2
    pairs = {}
    for i in range(2, len(key) - 1, 2):
        pairs[key[i]] = key[i + 1]
    try:
        frame = int(key[1])
    except ValueError:
        return None
    return {
        "frame": frame,
        "e": pairs.get("e", "?"),
        "x": pairs.get("x", "?"),
        "y": pairs.get("y", "?"),
        "dmg": pairs.get("dmg", "?"),
        "key": tuple(key),
        "raw": line,
    }


def load_segments(path):
    """Split the hash file into segments; a new segment starts when the frame number goes down."""
    segments = []
    current = []
    prev_frame = None
    for line in read_lines(path):
        rec = parse_hash_line(line)
        if rec is None:
            continue
        if prev_frame is not None and rec["frame"] < prev_frame:
            segments.append(current)
            current = []
        current.append(rec)
        prev_frame = rec["frame"]
    if current:
        segments.append(current)
    return segments


def seg_stats(seg):
    frames = set(r["frame"] for r in seg)
    entries = sorted(set(r["e"] for r in seg))
    return len(frames), entries


def entry_motion(seg):
    """Per entry: distinct (x,y) positions and distinct dmg values."""
    per = {}
    for r in seg:
        d = per.setdefault(r["e"], {"xy": set(), "dmg": set()})
        d["xy"].add((r["x"], r["y"]))
        d["dmg"].add(r["dmg"])
    return per


def compare_segment_pair(idx, sa, sb):
    print("-- segment %d --" % idx)
    fa, ea = seg_stats(sa)
    fb, eb = seg_stats(sb)
    print("  frames in A: %d   frames in B: %d" % (fa, fb))
    print("  entries (e) A: %s   B: %s" % (",".join(ea), ",".join(eb)))
    n = min(len(sa), len(sb))
    ident = 0
    first_diff = None
    for i in range(n):
        if sa[i]["key"] == sb[i]["key"]:
            ident += 1
        elif first_diff is None:
            first_diff = i
    print("  lines A: %d   lines B: %d   compared: %d   identical: %d" % (len(sa), len(sb), n, ident))
    if first_diff is not None:
        print("  first differing line index %d (frame A %d e %s / frame B %d e %s)"
              % (first_diff, sa[first_diff]["frame"], sa[first_diff]["e"],
                 sb[first_diff]["frame"], sb[first_diff]["e"]))
        print("    A: " + clip(sa[first_diff]["raw"]))
        print("    B: " + clip(sb[first_diff]["raw"]))
    else:
        print("  no differing line among the compared lines")
    if len(sa) != len(sb):
        print("  note: segment lengths differ (A %d, B %d)" % (len(sa), len(sb)))
    return {
        "idx": idx,
        "first_diff": first_diff,
        "compared": n,
        "frames_identical": len({r["frame"] for r in sa[:n]}),
        "sa": sa,
        "sb": sb,
    }


def print_motion(label, seg):
    print("  %s longest segment: motion per entry (distinct x,y | distinct dmg)" % label)
    for e, d in sorted(entry_motion(seg).items()):
        print("    e %s: %d positions | %d dmg values" % (e, len(d["xy"]), len(d["dmg"])))


def summarise_log(tag):
    path = os.path.join(LOG_DIR, "n11_%s.log" % tag)
    print("")
    print("== log summary: %s ==" % path)
    if not os.path.isfile(path):
        print("  (missing)")
        return
    lines = read_lines(path)

    ldn = [l for l in lines if "[online] ldn:" in l]
    print("[online] ldn: lines (%d total, showing up to %d):" % (len(ldn), MAX_LOG_LINES))
    for l in ldn[:MAX_LOG_LINES]:
        print("  " + clip(l))

    traffic = [l for l in lines if "[online] traffic:" in l]
    print("last [online] traffic: line:")
    print("  " + (clip(traffic[-1]) if traffic else "(none)"))

    for pat in DEBUG_PATTERNS:
        hits = [l for l in lines if pat in l]
        print("'%s' lines: %d" % (pat, len(hits)))
        for l in hits[:MAX_LOG_LINES]:
            print("  " + clip(l))
        if len(hits) > MAX_LOG_LINES:
            print("  ... %d more" % (len(hits) - MAX_LOG_LINES))

    seq = [l for l in lines if "input sequence:" in l]
    print("last 3 'input sequence:' lines:")
    if not seq:
        print("  (none)")
    for l in seq[-3:]:
        print("  " + clip(l))


def main(argv):
    if len(argv) != 3:
        print("Usage: python tests\\n3_sync_cmp.py <tagA> <tagB>")
        return 2
    tag_a, tag_b = argv[1], argv[2]
    path_a = os.path.join(LOG_DIR, "n11_%s.hash.txt" % tag_a)
    path_b = os.path.join(LOG_DIR, "n11_%s.hash.txt" % tag_b)
    for p in (path_a, path_b):
        if not os.path.isfile(p):
            print("missing hash file: %s" % p)
            return 1

    segs_a = load_segments(path_a)
    segs_b = load_segments(path_b)
    print("hash files: %s  |  %s" % (os.path.basename(path_a), os.path.basename(path_b)))
    print("segment counts: A %d   B %d" % (len(segs_a), len(segs_b)))
    print("")

    results = []
    for i in range(max(len(segs_a), len(segs_b))):
        if i >= len(segs_a) or i >= len(segs_b):
            print("-- segment %d -- present only in %s" % (i, "A" if i < len(segs_a) else "B"))
            results.append({"idx": i, "missing": True})
            continue
        results.append(compare_segment_pair(i, segs_a[i], segs_b[i]))
        print("")

    if segs_a and segs_b:
        longest_a = max(range(len(segs_a)), key=lambda k: len(segs_a[k]))
        longest_b = max(range(len(segs_b)), key=lambda k: len(segs_b[k]))
        print("longest segment: A #%d (%d lines), B #%d (%d lines)"
              % (longest_a, len(segs_a[longest_a]), longest_b, len(segs_b[longest_b])))
        print_motion("A", segs_a[longest_a])
        print_motion("B", segs_b[longest_b])
        print("")

    print("== verdict ==")
    for r in results:
        k = r["idx"]
        if r.get("missing"):
            print("NOT IN SYNC: segment %d exists in only one file" % k)
            continue
        n_frames = r["frames_identical"]
        if r["first_diff"] is None and r["compared"] > 0 and n_frames >= MIN_SYNC_FRAMES:
            print("SYNC: segment %d identical for %d frames" % (k, n_frames))
        else:
            if r["first_diff"] is not None:
                sa, sb, i = r["sa"], r["sb"], r["first_diff"]
                detail = ("first difference at line %d: frame %d e %s (A) vs frame %d e %s (B)"
                          % (i, sa[i]["frame"], sa[i]["e"], sb[i]["frame"], sb[i]["e"]))
            else:
                detail = ("no differing line, but only %d frames compared (need %d)"
                          % (n_frames, MIN_SYNC_FRAMES))
            print("NOT IN SYNC: segment %d, %s" % (k, detail))

    summarise_log(tag_a)
    summarise_log(tag_b)
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(errors="replace")
    except AttributeError:
        pass
    sys.exit(main(sys.argv))
