"""S13: one job at a time from tests\\s13_queue.txt (so that only one game runs at any moment). Each line is a job:
    batch <fighter> ...        python tests/s13_batch.py ...   (run, sweep, exclude/rebuild, install)
    hit <fighter> ...          python tests/s13_cover.py hit ...
    orig <fighter> ...         python tests/s13_cover.py orig ...
    normal <A> <B> [<C> <D>]   python tests/s13_cover.py normal ...
The first line is removed before it is run (and appended to tests\\logs\\s13_queue_done.txt with the time). The file may be extended
while this runs. Stops when tests\\s13_queue.stop exists or after 10 minutes with no job. Waits on nothing itself: the jobs wait on
tests\\QUIET_PLEASE inside the game runners."""
import os
import subprocess
import sys
import time

STUDY = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
Q = os.path.join(STUDY, 'tests', 's13_queue.txt')
DONE = os.path.join(STUDY, 'tests', 'logs', 's13_queue_done.txt')
SCRIPT = {'batch': 's13_batch.py', 'hit': None, 'orig': None, 'normal': None}


def pop():
    if not os.path.exists(Q):
        return None
    lines = [l for l in open(Q).read().splitlines() if l.strip() and not l.startswith('#')]
    if not lines:
        return None
    with open(Q, 'w') as f:
        f.write('\n'.join(lines[1:]) + ('\n' if lines[1:] else ''))
    return lines[0]


def main():
    idle = time.time()
    while not os.path.exists(os.path.join(STUDY, 'tests', 's13_queue.stop')):
        job = pop()
        if not job:
            if time.time() - idle > 600:
                break
            time.sleep(10)
            continue
        idle = time.time()
        words = job.split()
        if words[0] == 'batch':
            args = [sys.executable, os.path.join(STUDY, 'tests', 's13_batch.py')] + words[1:]
        else:
            args = [sys.executable, os.path.join(STUDY, 'tests', 's13_cover.py')] + words
        t0 = time.strftime('%H:%M:%S')
        r = subprocess.run(args, capture_output=True, text=True, cwd=STUDY)
        with open(DONE, 'a') as f:
            f.write('%s -> %s  %s  rc %d\n' % (t0, time.strftime('%H:%M:%S'), job, r.returncode))
            if r.returncode:
                f.write((r.stdout + r.stderr)[-600:] + '\n')


main()
