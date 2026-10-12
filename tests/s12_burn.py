"""Track V session 12: a CPU load for the priority-inversion test: <n> processes at normal priority spin for <seconds>,
starting after <delay> seconds.   python tests/s12_burn.py <n> <seconds> [delay]
No game content in this file."""
import multiprocessing
import sys
import time


def spin(until):
    x = 0
    while time.time() < until:
        for _ in range(200000):
            x += 1


if __name__ == '__main__':
    n, secs = int(sys.argv[1]), float(sys.argv[2])
    time.sleep(float(sys.argv[3]) if len(sys.argv) > 3 else 0)
    until = time.time() + secs
    ps = [multiprocessing.Process(target=spin, args=(until,)) for _ in range(n)]
    for p in ps:
        p.start()
    for p in ps:
        p.join()
    print('burn done: %d processes, %.0f s' % (n, secs))
