"""python nacp_extract.py <game or update .nsp> [out.nacp]

Finds the Control NCA of the title in the user's own dump, decrypts its RomFS (keys as romfs_extract.py:
~/.switch/prod.keys) and prints the save-data sizes of the application control property (NACP), which is
what nn::fs::GetSaveDataSize reports on the console. [doc] switchbrew "NACP": UserAccountSaveDataSize
@0x3080, UserAccountSaveDataJournalSize @0x3088, DeviceSaveDataSize @0x3090, ... (s64 each)."""
import struct, sys
import romfs_extract as R


class AnyNca(R.Nca):
    def __init__(self, nsp, name):
        nsp.program_nca = lambda: name
        R.Nca.__init__(self, nsp)


class Section:
    def __init__(self, nca, sec): self.nca, self.sec = nca, sec
    def read(self, offset, size): return self.nca.read(self.sec, offset, size)


def main():
    nsp = R.Nsp(sys.argv[1])
    for name in sorted(n for n in nsp.files if n.endswith('.nca')):
        try:
            nca = AnyNca(nsp, name)
        except Exception as e:
            print('skip %s: %s' % (name, e)); continue
        if nca.header[0x205] != 2:                      # content type: 0 Program, 1 Meta, 2 Control, ...
            continue
        sec = next(s for s in nca.sections if s['type'] == 0)       # RomFS
        fs = sec['fs']
        assert fs[8:12] == b'IVFC', 'control NCA: no IVFC header'
        level6, = struct.unpack_from('<Q', fs, 0x8 + 0x10 + 5 * 0x18)
        rom = Section(nca, sec)
        for path, off, size in R.walk(rom, level6):
            if path.endswith('control.nacp'):
                data = rom.read(off, size)
                if len(sys.argv) > 2: open(sys.argv[2], 'wb').write(data)
                names = ('UserAccountSaveDataSize', 'UserAccountSaveDataJournalSize', 'DeviceSaveDataSize', 'DeviceSaveDataJournalSize',
                         'BcatDeliveryCacheStorageSize')
                print('%s: control.nacp %d bytes, display version "%s"' % (name, size, data[0x3060:0x3070].split(b'\0')[0].decode()))
                for i, n in enumerate(names):
                    v, = struct.unpack_from('<q', data, 0x3080 + i * 8)
                    print('  %-32s 0x%x (%d)' % (n, v, v))
                for n, o in (('UserAccountSaveDataSizeMax', 0x3148), ('UserAccountSaveDataJournalSizeMax', 0x3150), ('CacheStorageSize', 0x3178),
                             ('CacheStorageJournalSize', 0x3180)):
                    v, = struct.unpack_from('<q', data, o)
                    print('  %-32s 0x%x (%d)' % (n, v, v))
                return
    print('no control.nacp found')


if __name__ == '__main__':
    main()
