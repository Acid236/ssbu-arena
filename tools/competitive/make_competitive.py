"""Competitive 1v1 set-up, data side: writes loose files (runtime/loose_files.c, SSBU_LOOSE_FILES=1) that change the
game's own parameter files, extracted from YOUR data.arc. Nothing of the game is in this file; the output is game
content derived from your dump and stays on your PC.

    python tools/competitive/make_competitive.py [--arc <data.arc>] [--out <build>/characters]

What it changes:
  ui/param/database/ui_stage_db.prc   only the 6 stages below can be selected (and drawn by "random"); every other
                                      stage row gets disp_order -1 and can_select false (the game's own way to hide a row)
  ui/param/database/ui_item_db.prc    no item is in the item switch list or in training (use_switch / use_training
                                      false, display orders -1), the Smash Ball included: nothing can appear at random.
                                      The fighters' own items (turnips, bombs, ...) do not come from this list.
  ui/param/database/ui_rule_db.prc    every preset ruleset: items off (item_switch), Final Smash meter off (charge 0)
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', 'nro'))
from prc import Prc  # noqa: E402

STAGES = ['BattleField', 'BattleFieldS', 'End', 'Poke_Stadium2', 'Animal_Village', 'Animal_City']
RANDOM = ['Random', 'RandomNormal', 'RandomBattleField', 'RandomEnd']
MOD = 'competitive'


def stage_db(src, dst):
    p = Prc(src)
    kept, hidden = [], 0
    for r in p.rows('db_root'):
        name = p.get(p.field(r, 'name_id'))
        order, sel = p.field(r, 'disp_order'), p.field(r, 'can_select')
        if name in STAGES:
            p.set(order, STAGES.index(name) + 1); p.set(sel, 1); kept.append(name)
        elif name in RANDOM:
            continue
        elif p.get(order) >= 0 or p.get(sel):
            p.set(order, -1); p.set(sel, 0); hidden += 1
    missing = set(STAGES) - set(kept)
    if missing: raise SystemExit('stage rows not found: %s' % ', '.join(sorted(missing)))
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    p.save(dst)
    print('ui_stage_db.prc: %d stages kept (%s), %d hidden -> %s' % (len(kept), ', '.join(kept), hidden, dst))


def item_db(src, dst):
    p = Prc(src)
    n = 0
    for r in p.rows('db_root'):
        for f, v in (('use_switch', 0), ('use_training', 0), ('switch_disp_order', -1), ('training_disp_order', -1)):
            o = p.field(r, f)
            if o is not None and p.get(o) != v: p.set(o, v); n += 1
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    p.save(dst)
    print('ui_item_db.prc: %d items, %d values changed -> %s' % (len(p.rows('db_root')), n, dst))


def rule_db(src, dst):
    p = Prc(src)
    rows = p.rows('db_root')
    for r in rows:
        p.set(p.field(r, 'item_switch'), 0)
        p.set(p.field(r, 'charge'), 0)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    p.save(dst)
    print('ui_rule_db.prc: %d presets with items off and the Final Smash meter off -> %s' % (len(rows), dst))


def main():
    root = os.path.normpath(os.path.join(HERE, '..', '..'))
    ap = argparse.ArgumentParser()
    ap.add_argument('--arc', default=None, help='data.arc (default: SSBU_ARC, or the romfs of build/state.json)')
    ap.add_argument('--out', default=os.path.join(root, 'build', 'characters'))
    a = ap.parse_args()
    arc = a.arc or os.environ.get('SSBU_ARC')
    if not arc:
        import json
        st = json.load(open(os.path.join(root, 'build', 'state.json')))
        arc = os.path.join(st['dump']['romfs'], 'data.arc')
    os.environ['SSBU_ARC'] = arc
    import arc_extract as ax
    A = ax.Arc(arc)
    tmp = os.path.join(root, 'build', 'competitive_work')
    os.makedirs(tmp, exist_ok=True)
    for name, fn in (('ui_stage_db', stage_db), ('ui_item_db', item_db), ('ui_rule_db', rule_db)):
        src = os.path.join(tmp, name + '.prc')
        open(src, 'wb').write(A.get('ui/param/database/%s.prc' % name))
        fn(src, os.path.join(a.out, MOD, 'ui', 'param', 'database', name + '.prc'))


if __name__ == '__main__':
    main()
