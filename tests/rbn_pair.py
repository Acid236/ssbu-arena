"""R3 online rollback: two games on this PC, host + join over net_relay (the host's in-game lobby), a scripted match.
    python tests/rbn_pair.py <tag> [KEY=VALUE ...]      (KEY=VALUE for both games; H:KEY=VALUE / J:KEY=VALUE for one)
Defaults: exe N5_EXE=ssbu_rbn6r.exe, 1v1 Mario v Donkey Kong (port 2 human = the other game), Final Destination, link
simulation SSBU_NET_SIM=75 on both (150 ms round trip), bots 7 / 11, UDP port 39520, run ends at the end of the match.
Runs tests/n11_run.py twice (tags <tag>h, <tag>j), then tests/rbn_cmp.py on their SSBU_RB_NET_LOG files and prints the
rollback / timing lines of both r1 logs. Waits while tests/QUIET_PLEASE exists. No game content in this file."""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
STUDY = os.path.dirname(HERE)
LOGS = os.path.join(HERE, 'logs')


def main():
    tag = sys.argv[1]
    both, own = {}, {'h': {}, 'j': {}}
    for a in sys.argv[2:]:
        if a[:2] in ('H:', 'J:'):
            k, v = a[2:].split('=', 1)
            own[a[0].lower()][k] = v
        else:
            k, v = a.split('=', 1)
            both[k] = v
    while os.path.exists(os.path.join(HERE, 'QUIET_PLEASE')):
        print('QUIET_PLEASE: waiting', flush=True)
        time.sleep(25)
    base = dict(N5_EXE='ssbu_rbn6r.exe', N5_SAVE='../userdata_completo', N5_SEQ='seq_completo.txt', SSBU_NRO_BIN='nro_bin_eh_o2',
                SSBU_DEBUG_END='2400', N5_SECS='480', SSBU_NET_SIM='75', SSBU_RB_NET='net', SSBU_ONLINE_STUN='off', SSBU_ONLINE_UPNP='off', SSBU_ONLINE_LOOPBACK='1',
                N5_STOP_ON='fight.off', SSBU_DEBUG_MATCH='p1=mario,p2=donkey,p2=human,stage=end')
    base.update(both)
    port = base.pop('RBN_PORT', '39520')
    stagger = float(base.pop('RBN_STAGGER', '3'))      # hs12: seconds between the two starts (two boots at once sometimes miss the title screen)
    procs = []
    for side in ('h', 'j'):
        t = tag + side
        env = dict(base)
        env.update(SSBU_ONLINE='host:' + port if side == 'h' else 'join:127.0.0.1:' + port, SSBU_RB_NET_BOT='7' if side == 'h' else '11',
                   SSBU_R1_LOG='tests/logs/r1_%s.txt' % t, SSBU_RB_NET_LOG='tests/logs/rbn_%s.txt' % t)
        env.update(own[side])
        out = open(os.path.join(LOGS, 'rbn_pair_%s.out' % t), 'w')
        procs.append((t, subprocess.Popen([sys.executable, os.path.join(HERE, 'n11_run.py'), t] + ['%s=%s' % kv for kv in env.items()],
                                          cwd=STUDY, stdout=out, stderr=subprocess.STDOUT), out))
        time.sleep(stagger)
    for t, p, out in procs:
        p.wait()
        out.close()
        print(open(os.path.join(LOGS, 'rbn_pair_%s.out' % t)).readline().strip())
    subprocess.run([sys.executable, os.path.join(HERE, 'rbn_cmp.py'), os.path.join(LOGS, 'rbn_%sh.txt' % tag), os.path.join(LOGS, 'rbn_%sj.txt' % tag)])
    for t, _, _ in procs:
        print('==', t)
        lines = open(os.path.join(LOGS, 'r1_%s.txt' % t), errors='replace').read().splitlines()
        keep = [l for l in lines if 'start barrier' in l or 'RB NET report' in l or ('RB NET TIMING' in l and 'with rollback' in l) or '[rbnet] report' in l or 'DESYNC' in l
                or 'RING rebase' in l or 'match start, base' in l or 'not agreed' in l or 'RB NET: match' in l or 'ring memory' in l
                or ('RB NET TIMING' in l and 'tick to tick' in l)]
        for l in keep:                                # (hs12: one report per match now)
            print('  ' + l[:330])
        for l in open(os.path.join(LOGS, 'n11_%s.log' % t), errors='replace'):      # rbn9: the match handshake and the match block check
            if 'handshake' in l and ('agreed' in l or 'FAILED' in l or 'the match:' in l or 'no panel' in l) or 'match block check' in l or 'notice drawn' in l or 'handshake: stage' in l or 'after the start barrier' in l                     or '[rbnet] match' in l or 'debug panels' in l:
                print('  ' + l.rstrip()[:330])


if __name__ == '__main__':
    main()
