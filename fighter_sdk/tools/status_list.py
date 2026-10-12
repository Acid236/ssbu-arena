"""python status_list.py mario : the status scripts a module registers (status kind, line, function offset, size)."""
import sys

import acmd_decomp as A
import census
import luaconst


class RegExec(A.Exec):
    def scalar(self, v, name):
        if v[0] in ('img', 'undef'):
            return v
        return A.Exec.scalar(self, v, name)


def main():
    mod = A.Module(sys.argv[1])
    r = mod.r
    consts = luaconst.table_names()
    n = mod.nro

    def cname(e):
        if e[0] == 'lv' and e[2][0] == 'luaconst':
            return consts[e[2][1]][0] or 'const#%d' % e[2][1]
        if e[0] == 'lv' and e[2][0] == 'int':
            return str(e[2][1])
        return str(e)

    for i, cl in sorted(r['calls'].items()):
        if not any(n.plt.get(t) == census.SET_STATUS for pc, t in cl):
            continue
        f = r['fdes'][i][0]
        try:
            ex = RegExec(mod, f, 'macro').run()
        except A.NotMechanical as e:
            print('registering function +0x%x: not understood (%s)' % (f, e))
            continue
        print('registering function +0x%x' % f)
        for nd in ex.nodes:
            if nd['kind'] == 'call' and nd['sym'] == census.SET_STATUS:
                a = nd['args']
                off = a[3][1] if a[3][0] == 'img' else 0
                print('  %-50s %-42s +0x%x  %d bytes' % (cname(a[1]), cname(a[2]), off, n.func_size(off) or 0))


main()
