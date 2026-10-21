"""R3 lwr (owner 2026-10-21: rollback in Local Wireless rooms too): two games in ONE Local Wireless room, through a lobby on
this PC (tools/net/ssbu_lobby.py, the public code). Game A makes the room (tests/seq_lwr_host.txt: room, waiting stage, then
L + R until the room match is set up, then runs off the stage), game B joins it (tests/seq_lwr_join.txt). Both with rollback
on by default; then tests/rbn_cmp.py on the SSBU_RB_NET_LOG files (a rollback room match) and tests/cmp_room.py on the fight
hashes (the room match, whoever plays it).
    python tests/lwr_pair.py <tag> [KEY=VALUE ...]      (KEY=VALUE for both games; A:KEY=VALUE / B:KEY=VALUE for one)
A:SSBU_RB_NET=(unset) = the room maker without rollback (the off side). Defaults: N5_EXE=ssbu_lw1.exe, ../userdata_completo
(COPIED by n11_run.py), bots 7 / 11, SSBU_NET_SIM=75 (150 ms round trip), LWR_PORT=<lobby port> (default 39551). The second
game starts 25 s after the first (two boots at once overload this PC's GPU driver). Waits while tests/QUIET_PLEASE exists.
No game content in this file."""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
STUDY = os.path.dirname(HERE)
LOGS = os.path.join(HERE, 'logs')


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
    port = both.pop('LWR_PORT', '39551')
    lobby_py = both.pop('LWR_LOBBY', os.path.join(STUDY, 'tools', 'net', 'ssbu_lobby.py'))
    lobby_log = open(os.path.join(LOGS, 'lwr_lobby_%s.log' % tag), 'w')
    lobby = subprocess.Popen([sys.executable, '-u', lobby_py, '--bind', '127.0.0.1', '--port', port, '--verbose', '--stats', '0'],
                             cwd=STUDY, stdout=lobby_log, stderr=subprocess.STDOUT)
    time.sleep(1.0)
    base = dict(N5_EXE='ssbu_lw1.exe', N5_SAVE='../userdata_completo', SSBU_NRO_BIN='nro_bin_eh_o2', N5_SECS='600', SSBU_NET_SIM='75',
                SSBU_RB_NET='net', SSBU_ONLINE='127.0.0.1:' + port, SSBU_ONLINE_STUN='off', SSBU_ONLINE_UPNP='off', SSBU_ONLINE_LOOPBACK='1',
                SSBU_RB_NET_HS_WAIT='60')
    base.update(both)
    procs = []
    try:
        for side, bot, name, seq in (('a', '7', 'RoomMaker', 'seq_lwr_host.txt'), ('b', '11', 'RoomJoiner', 'seq_lwr_join.txt')):
            t = tag + side
            env = dict(base)
            env.update(N5_SEQ=seq, SSBU_RB_NET_BOT=bot, SSBU_ONLINE_NAME=name, SSBU_R1_LOG='tests/logs/r1_%s.txt' % t, SSBU_RB_NET_LOG='tests/logs/rbn_%s.txt' % t)
            env.update(own[side])
            out = open(os.path.join(LOGS, 'lwr_pair_%s.out' % t), 'w')
            procs.append((t, subprocess.Popen([sys.executable, os.path.join(HERE, 'n11_run.py'), t] + ['%s=%s' % kv for kv in env.items()],
                                              cwd=STUDY, stdout=out, stderr=subprocess.STDOUT), out))
            if side == 'a':
                time.sleep(25)
        for t, p, out in procs:
            p.wait()
            out.close()
    finally:
        lobby.terminate()
        lobby.wait(10)
        lobby_log.close()
    for t, _, _ in procs:
        print('==', t, open(os.path.join(LOGS, 'lwr_pair_%s.out' % t)).readline().strip()[:200])
    ra, rb = os.path.join(LOGS, 'rbn_%sa.txt' % tag), os.path.join(LOGS, 'rbn_%sb.txt' % tag)
    if os.path.exists(ra) and os.path.exists(rb) and os.path.getsize(ra) and os.path.getsize(rb):
        subprocess.run([sys.executable, os.path.join(HERE, 'rbn_cmp.py'), ra, rb])
    subprocess.run([sys.executable, os.path.join(HERE, 'cmp_room.py'), LOGS, tag + 'a', tag + 'b'])
    for t, _, _ in procs:
        print('==', t)
        r1 = os.path.join(LOGS, 'r1_%s.txt' % t)
        if os.path.exists(r1):
            for l in open(r1, errors='replace'):
                if ('RB NET report: ' in l and ('real frames' in l or 'stalls' in l)) or 'start barrier' in l or 'Local Wireless' in l or 'RB NET: match start' in l:
                    print('  ' + l.rstrip()[:300])
        for l in open(os.path.join(LOGS, 'n11_%s.log' % t), errors='replace'):
            if ('[rbnet]' in l and ('handshake' in l or 'report' in l or 'match ' in l or 'messages go to' in l or 'after the start barrier' in l
                                    or 'DESYNC' in l or 'room' in l)) or ('ldn:' in l and ('room' in l or 'state' in l)) or 'HOST EXCEPTION' in l or 'GUEST TRAP' in l:
                if 'still waiting' not in l:
                    print('  ' + l.rstrip()[:300])


if __name__ == '__main__':
    main()
