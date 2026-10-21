"""R3 net3 (goal 3): a ROLLBACK match started from the lobby without a room code. A lobby on this PC (tools/net/ssbu_lobby.py,
the public code), two games in lobby mode (SSBU_ONLINE=127.0.0.1:<port>), both with rollback on: each enters Smash versus
(input sequence + SSBU_DEBUG_MATCH, as tests/rbn_pair.py); at the match set-up each game asks the lobby for an opponent
(MATCH op 2), the lobby pairs them (the one that searched first is player 1), the handshake agrees on the match and the
match is played with rollback. Then tests/rbn_cmp.py on both games' SSBU_RB_NET_LOG files.
    python tests/lbr_pair.py <tag> [KEY=VALUE ...]      (KEY=VALUE for both games; A:KEY=VALUE / B:KEY=VALUE for one)
Defaults as rbn_pair.py: N5_EXE=ssbu_n3b.exe, ../userdata_completo (COPIED by n11_run.py), seq_completo.txt, Mario v DK on
Final Destination, bots 7 / 11, SSBU_NET_SIM=40 on both (80 ms round trip through the lobby). LBR_PORT=<lobby port>
(default 39541), LBR_LOBBY=<lobby .py>. The second game starts once the first searches (two boots at once overload this
PC's GPU driver). Waits while tests/QUIET_PLEASE exists. No game content in this file."""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
STUDY = os.path.dirname(HERE)
LOGS = os.path.join(HERE, 'logs')


def has(path, what):
    return os.path.exists(path) and what in open(path, errors='replace').read()


def main():
    tag = sys.argv[1]
    both, own = {}, {'a': {}, 'b': {}}
    for a in sys.argv[2:]:
        if a[:2] in ('A:', 'B:'):
            k, v = a[2:].split('=', 1)
            own[a[0].lower()][k] = v
        else:
            k, v = a.split('=', 1)
            both[k] = v
    while os.path.exists(os.path.join(HERE, 'QUIET_PLEASE')):
        print('QUIET_PLEASE: waiting', flush=True)
        time.sleep(25)
    port = both.pop('LBR_PORT', '39541')
    lobby_py = both.pop('LBR_LOBBY', os.path.join(STUDY, 'tools', 'net', 'ssbu_lobby.py'))
    lobby_log = open(os.path.join(LOGS, 'lbr_lobby_%s.log' % tag), 'w')
    lobby = subprocess.Popen([sys.executable, '-u', lobby_py, '--bind', '127.0.0.1', '--port', port, '--verbose', '--stats', '0', '--search-secs', '900'],
                             cwd=STUDY, stdout=lobby_log, stderr=subprocess.STDOUT)
    time.sleep(1.0)
    base = dict(N5_EXE='ssbu_n3b.exe', N5_SAVE='../userdata_completo', N5_SEQ='seq_completo.txt', SSBU_NRO_BIN='nro_bin_eh_o2',
                SSBU_DEBUG_END='2400', N5_SECS='900', SSBU_NET_SIM='40', SSBU_RB_NET='net', SSBU_ONLINE='127.0.0.1:' + port,
                SSBU_ONLINE_STUN='off', SSBU_ONLINE_UPNP='off', SSBU_ONLINE_LOOPBACK='1', SSBU_RB_NET_HS_WAIT='900',
                N5_STOP_ON='fight.off', SSBU_DEBUG_MATCH='p1=mario,p2=donkey,p2=human,stage=end')
    base.update(both)
    procs = []
    try:
        for side, bot, name in (('a', '7', 'LobbyA'), ('b', '11', 'LobbyB')):
            t = tag + side
            env = dict(base)
            env.update(SSBU_RB_NET_BOT=bot, SSBU_ONLINE_NAME=name, SSBU_R1_LOG='tests/logs/r1_%s.txt' % t, SSBU_RB_NET_LOG='tests/logs/rbn_%s.txt' % t)
            env.update(own[side])
            out = open(os.path.join(LOGS, 'lbr_pair_%s.out' % t), 'w')
            procs.append((t, subprocess.Popen([sys.executable, os.path.join(HERE, 'n11_run.py'), t] + ['%s=%s' % kv for kv in env.items()],
                                              cwd=STUDY, stdout=out, stderr=subprocess.STDOUT), out))
            if side == 'a':
                gl, t0 = os.path.join(LOGS, 'n11_%s.log' % t), time.time()
                while time.time() - t0 < 400 and procs[0][1].poll() is None and not has(gl, 'asking the lobby for an opponent'):
                    time.sleep(2)
                time.sleep(5)
        for t, p, out in procs:
            p.wait()
            out.close()
    finally:
        lobby.terminate()
        lobby.wait(10)
        lobby_log.close()
    for t, _, _ in procs:
        print('==', t, open(os.path.join(LOGS, 'lbr_pair_%s.out' % t)).readline().strip()[:200])
    subprocess.run([sys.executable, os.path.join(HERE, 'rbn_cmp.py'), os.path.join(LOGS, 'rbn_%sa.txt' % tag), os.path.join(LOGS, 'rbn_%sb.txt' % tag)])
    for t, _, _ in procs:
        print('==', t)
        r1 = os.path.join(LOGS, 'r1_%s.txt' % t)
        if os.path.exists(r1):
            for l in open(r1, errors='replace'):
                if ('RB NET report: ' in l and 'real frames' in l) or ('RB NET TIMING' in l and ('with rollback' in l or 'tick to tick' in l)) or 'start barrier' in l or 'rollback parts' in l:
                    print('  ' + l.rstrip()[:300])
        for l in open(os.path.join(LOGS, 'n11_%s.log' % t), errors='replace'):
            if ('[rbnet]' in l and ('handshake' in l and ('agreed' in l or 'FAILED' in l or 'found an opponent' in l or 'asking the lobby' in l) or 'report' in l or 'match 1' in l
                                    or 'messages go to' in l or 'after the start barrier' in l or 'DESYNC' in l)) or '[online] match' in l:
                print('  ' + l.rstrip()[:300])
    print('== lobby')
    for l in open(os.path.join(LOGS, 'lbr_lobby_%s.log' % tag), errors='replace'):
        if 'stats' not in l and 'scanned' not in l:
            print('  ' + l.rstrip()[:300])


if __name__ == '__main__':
    main()
