"""tiny exact-replace helper that respects the file's line endings: python tools_audit/patch.py <file> <patchfile>
patchfile: blocks separated by lines '@@@@'; each block is OLD, a line '====', NEW. Every OLD must occur exactly once."""
import sys
p, pf = sys.argv[1], sys.argv[2]
s = open(p, 'r', newline='', encoding='latin-1').read()
nl = '\r\n' if '\r\n' in s else '\n'
blocks = open(pf, 'r', encoding='latin-1').read().split('\n@@@@\n')
for b in blocks:
    if not b.strip(): continue
    old, new = b.split('\n====\n')
    old, new = old.replace('\n', nl), new.rstrip('\n').replace('\n', nl)
    old = old.rstrip('\r\n') if not old.endswith(nl + nl) else old
    if s.count(old) != 1: print('PATCH FAILED (%d matches):\n%s' % (s.count(old), old[:300])); sys.exit(1)
    s = s.replace(old, new)
open(p, 'w', newline='', encoding='latin-1').write(s)
print('patched', p, len(blocks), 'block(s)')
