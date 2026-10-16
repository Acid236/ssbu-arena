"""Round "four players": compare two SSBU_AUDIO_HASH files (one line per buffer handed to the audio device).
    python tests/p15_pcm_compare.py <a.txt> <b.txt>
The audio thread runs on wall time and the game on frames, so two runs of the SAME exe do not give the same sequence
(a sound starts in another buffer). What two runs with the same mixer arithmetic share: buffers whose content is the
same in both (same samples -> same hash), in the same order. Printed: buffers, non-silent buffers, distinct non-silent
hashes, how many non-silent hashes of A occur in B, and the longest run of consecutive non-silent buffers that is
identical in both. A mixer that rounds differently shares (almost) nothing. No game content."""
import sys


def load(p):
    rows = []
    for line in open(p):
        f = line.split()
        if len(f) == 4:
            rows.append((int(f[2]), f[3]))
    return rows


a, b = load(sys.argv[1]), load(sys.argv[2])
na = [h for peak, h in a if peak]
nb = [h for peak, h in b if peak]
sb = set(nb)
common = sum(1 for h in na if h in sb)
pos = {}
for i, h in enumerate(nb):
    pos.setdefault(h, []).append(i)
best = 0
prev = {}
for i, h in enumerate(na):
    cur = {}
    for j in pos.get(h, ()):
        cur[j] = prev.get(j - 1, 0) + 1
        if cur[j] > best:
            best = cur[j]
    prev = cur
print('A: %d buffers, %d with sound, %d distinct | B: %d buffers, %d with sound, %d distinct' % (len(a), len(na), len(set(na)), len(b), len(nb), len(sb)))
print('non-silent buffers of A whose exact content occurs in B: %d of %d (%.1f %%); longest identical consecutive run: %d buffers (%.1f s)'
      % (common, len(na), 100.0 * common / max(1, len(na)), best, best * 512 / 48000.0))
