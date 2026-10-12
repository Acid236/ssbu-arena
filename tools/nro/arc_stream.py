"""Stream section of data.arc (movies, bgm): list entries with names from ParamLabels.csv, extract one.
  python arc_stream.py list [substring]
  python arc_stream.py get <path-or-0xhash> <out>
Layout from reference/smash-arc src/filesystem.rs: after the FileSystemHeader (0x100 aligned) comes
StreamHeader {quick_dir_count, stream_hash_count, stream_file_index_count, stream_offset_entry_count},
quick_dirs[], stream_hash_to_entries[] (HashToIndex: u32 crc, u8 len, u24 index), stream_entries[]
(HashToIndex path + u32 flags), stream_file_indices[u32], stream_datas[] {u64 size, u64 offset}.
StreamEntry.path.index -> stream_file_indices[index] -> stream_datas[that] (offset is absolute in the file)."""
import os, struct, sys
sys.path.insert(0, r'<project>/recomp-study\ro_study')
import arc_extract
LABELS = os.environ.get('PARAM_LABELS') or os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'reference', 'param-labels', 'ParamLabels.csv')

def load_labels():
    names = {}
    with open(LABELS, 'r', encoding='utf-8', errors='replace') as f:
        for line in f:
            h, _, n = line.strip().partition(',')
            try: names[int(h, 16)] = n
            except ValueError: pass
    return names

class Streams:
    def __init__(self, arc):
        t = arc.t
        p = 0x100
        qd, sh, sfi, soe = struct.unpack_from('<4I', t, p); p += 16
        p += qd * 12
        self.o_h2e = p; p += sh * 8
        self.o_entries = p; p += sh * 12
        self.o_fidx = p; p += sfi * 4
        self.o_datas = p; p += soe * 16
        self.n = sh
        self.t = t
        self.arc = arc
    def entry(self, i):
        q, flags = struct.unpack_from('<QI', self.t, self.o_entries + i * 12)
        h, idx = arc_extract.h2i(q)
        fi, = struct.unpack_from('<I', self.t, self.o_fidx + idx * 4)
        size, off = struct.unpack_from('<2Q', self.t, self.o_datas + fi * 16)
        return h, flags, size, off
    def find(self, h):
        for i in range(self.n):
            e = self.entry(i)
            if e[0] == h: return e
        return None

if __name__ == '__main__':
    arc = arc_extract.Arc()
    st = Streams(arc)
    cmd = sys.argv[1]
    names = load_labels()
    if cmd == 'list':
        sub = sys.argv[2] if len(sys.argv) > 2 else ''
        for i in range(st.n):
            h, flags, size, off = st.entry(i)
            n = names.get(h, '')
            if sub in n:
                print('%012x %-60s flags=%x size=%d off=%#x' % (h, n or '?', flags, size, off))
    else:
        key = sys.argv[2]
        h = int(key, 16) if key.startswith('0x') else arc_extract.hash40(key)
        e = st.find(h)
        if not e: sys.exit('not found')
        h, flags, size, off = e
        arc.f.seek(off)
        data = arc.f.read(size)
        open(sys.argv[3], 'wb').write(data)
        print('wrote', sys.argv[3], len(data), 'bytes, first bytes', data[:16].hex())
