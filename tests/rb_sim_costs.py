"""Side-by-side cost tables for the R1 ring-rollback simulation logs.

Usage:
    python tests\\rb_sim_costs.py <r1 log> [<r1 log> ...]

Example:
    python tests\\rb_sim_costs.py recomp-study\\tests\\logs\\r1_rgs1.txt recomp-study\\tests\\logs\\r1_rgs2.txt

Each log becomes one column. The column header is the log's tag: the file name
without the extension and without the "r1_" prefix (r1_rgs6.txt -> rgs6).

A log may contain the report lines several times (periodic reports); only the
LAST occurrence of each line kind is used. Text before "r1:" (timestamps and so
on) is ignored. A value that a log does not contain is printed as "-".

Tables printed as Markdown, times in ms:
  1. Captures: counts, pool memory, capture median/mean/p99, the four parts,
     pages (+ extras) and MB.
  2. Load per k: "median / mean / p99 (hold, undo + page copy)" for each k.
  3. Passes: real and re-run counts, means and medians, the four parts of each,
     and the kick skip mask.
  4. 7-frame rollback budget = load(k=7 median) + 7 x re-run pass mean
     + 7 x capture median (re-captures on the way), and whether it is under 16.7 ms.

Standard library only. Does not touch the game or any other file.
"""

import re
import sys
from pathlib import Path

NUM = r"(-?\d+(?:\.\d+)?)"
BUDGET_MS = 16.7


def rx(pattern):
    return re.compile(pattern.replace("NUM", NUM))


PATTERNS = {
    "report": rx(
        r"r1: RING report: (?P<captures>\d+) captures \((?P<skipped>\d+) skipped[^)]*\), "
        r"(?P<loads>\d+) loads, (?P<pool_bufs>\d+) pool buffers made \((?P<pool_mb>NUM) MB\)"
    ),
    "capture": rx(
        r"r1: RING capture: median (?P<median>NUM) mean (?P<mean>NUM) p99 (?P<p99>NUM) ms; "
        r"parts \(means\): hold (?P<hold>NUM), sweep \+ undo log (?P<sweep>NUM), "
        r"page copy \(parallel\) (?P<copy>NUM), "
        r"fibers \+ threads \+ command buffers \+ let go (?P<let_go>NUM); "
        r"pages (?P<pages>\d+) \+ extras (?P<extras>\d+) mean \((?P<mb>NUM) MB\)"
    ),
    "load": rx(
        r"r1: RING load k (?P<k>\d+) \((?P<n>\d+)\): median (?P<median>NUM) "
        r"mean (?P<mean>NUM) p99 (?P<p99>NUM) ms \(hold (?P<hold>NUM), "
        r"undo \+ page copy (?P<copy>NUM), rest (?P<rest>NUM)\); "
        r"pages copied (?P<pages>NUM) mean \((?P<mb>NUM) MB\)"
    ),
    "counts": rx(
        r"r1: RB SIM: (?P<rollbacks>\d+) rollbacks \(k: [^)]*\), "
        r"captures failed (?P<cfail>\d+), re-run pads missing (?P<pads>\d+), "
        r"passes with more than one poll (?P<multi>\d+)"
    ),
    "passes": rx(
        r"r1: RB SIM passes \([^)]*\): real (?P<real_n>\d+) mean (?P<real_mean>NUM) "
        r"median (?P<real_median>NUM) ms; re-run (?P<rerun_n>\d+) mean (?P<rerun_mean>NUM) "
        r"median (?P<rerun_median>NUM) ms \(kick skip mask in re-run passes but the last: "
        r"(?P<skip>\d+)\)"
    ),
    "real_parts": rx(
        r"r1: RB SIM real passes \((?P<n>\d+)\), means ms: pass start -> poll (?P<to_poll>NUM), "
        r"poll -> frame end (?P<poll_to_end>NUM), frame end call (?P<end_call>NUM), "
        r"frame end -> safe point (?P<end_to_safe>NUM)"
    ),
    "rerun_parts": rx(
        r"r1: RB SIM re-run passes \((?P<n>\d+)\), means ms: pass start -> poll (?P<to_poll>NUM), "
        r"poll -> frame end (?P<poll_to_end>NUM), frame end call (?P<end_call>NUM), "
        r"frame end -> safe point (?P<end_to_safe>NUM)"
    ),
}


def parse_log(path):
    """Return the last match of each report line kind; loads are keyed by k."""
    data = {kind: None for kind in PATTERNS}
    data["loads"] = {}
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        for kind, pattern in PATTERNS.items():
            match = pattern.search(line)
            if not match:
                continue
            if kind == "load":
                fields = match.groupdict()
                data["loads"][int(fields["k"])] = fields
            else:
                data[kind] = match.groupdict()
    return data


def field(record, key):
    if record is None or record.get(key) is None:
        return "-"
    return record[key]


def budget(data):
    """7-frame rollback budget in ms as a float, or None when an input is missing."""
    load7 = data["loads"].get(7)
    passes = data["passes"]
    capture = data["capture"]
    if not (load7 and passes and capture):
        return None
    return (float(load7["median"]) + 7 * float(passes["rerun_mean"])
            + 7 * float(capture["median"]))


def md_table(title, headers, rows):
    lines = [f"## {title}", ""]
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("|" + "|".join(["---"] * len(headers)) + "|")
    for label, cells in rows:
        lines.append("| " + " | ".join([label] + list(cells)) + " |")
    lines.append("")
    return "\n".join(lines)


def tag_of(path):
    stem = Path(path).stem
    return stem[3:] if stem.startswith("r1_") else stem


def main(argv):
    if not argv:
        print(__doc__, file=sys.stderr)
        return 2
    tags = []
    logs = []
    for path in argv:
        if not Path(path).is_file():
            print(f"error: no such log: {path}", file=sys.stderr)
            return 1
        tags.append(tag_of(path))
        logs.append(parse_log(path))
    headers = ["metric"] + tags

    def row(label, getter):
        return (label, [str(getter(d)) for d in logs])

    out = ["# R1 rollback cost comparison (ms)", ""]

    # 1. Captures
    rep = lambda d, k: field(d["report"], k)  # noqa: E731
    cap = lambda d, k: field(d["capture"], k)  # noqa: E731
    out.append(md_table("1. Captures", headers, [
        row("captures", lambda d: rep(d, "captures")),
        row("skipped (thread not at a wait)", lambda d: rep(d, "skipped")),
        row("loads", lambda d: rep(d, "loads")),
        row("pool MB", lambda d: rep(d, "pool_mb")),
        row("pool buffers made", lambda d: rep(d, "pool_bufs")),
        row("capture median", lambda d: cap(d, "median")),
        row("capture mean", lambda d: cap(d, "mean")),
        row("capture p99", lambda d: cap(d, "p99")),
        row("part: hold", lambda d: cap(d, "hold")),
        row("part: sweep + undo log", lambda d: cap(d, "sweep")),
        row("part: page copy (parallel)", lambda d: cap(d, "copy")),
        row("part: fibers + threads + cmd buffers + let go", lambda d: cap(d, "let_go")),
        row("pages + extras (mean)", lambda d: (
            f"{cap(d, 'pages')} + {cap(d, 'extras')}" if d["capture"] else "-")),
        row("pages MB (mean)", lambda d: cap(d, "mb")),
    ]))

    # 2. Load per k
    ks = sorted(set(range(1, 8)).union(*[set(d["loads"]) for d in logs]))

    def load_cell(d, k):
        rec = d["loads"].get(k)
        if not rec:
            return "-"
        return (f"{rec['median']} / {rec['mean']} / {rec['p99']} "
                f"({rec['hold']}, {rec['copy']})")

    out.append(md_table(
        "2. Load per k: median / mean / p99 (hold, undo + page copy)",
        ["k"] + tags,
        [(str(k), [load_cell(d, k) for d in logs]) for k in ks],
    ))

    # 3. Passes
    pas = lambda d, k: field(d["passes"], k)  # noqa: E731
    rp = lambda d, k: field(d["real_parts"], k)  # noqa: E731
    rr = lambda d, k: field(d["rerun_parts"], k)  # noqa: E731
    out.append(md_table("3. Passes (safe point to safe point)", headers, [
        row("real passes (n)", lambda d: pas(d, "real_n")),
        row("real mean", lambda d: pas(d, "real_mean")),
        row("real median", lambda d: pas(d, "real_median")),
        row("real: pass start -> poll", lambda d: rp(d, "to_poll")),
        row("real: poll -> frame end", lambda d: rp(d, "poll_to_end")),
        row("real: frame end call", lambda d: rp(d, "end_call")),
        row("real: frame end -> safe point", lambda d: rp(d, "end_to_safe")),
        row("re-run passes (n)", lambda d: pas(d, "rerun_n")),
        row("re-run mean", lambda d: pas(d, "rerun_mean")),
        row("re-run median", lambda d: pas(d, "rerun_median")),
        row("re-run: pass start -> poll", lambda d: rr(d, "to_poll")),
        row("re-run: poll -> frame end", lambda d: rr(d, "poll_to_end")),
        row("re-run: frame end call", lambda d: rr(d, "end_call")),
        row("re-run: frame end -> safe point", lambda d: rr(d, "end_to_safe")),
        row("kick skip mask in re-run passes but the last", lambda d: pas(d, "skip")),
    ]))

    # 4. Budget
    def budget_cells(d):
        load7 = d["loads"].get(7)
        passes = d["passes"]
        capture = d["capture"]
        return {
            "load7": load7["median"] if load7 else "-",
            "rerun7": f"{7 * float(passes['rerun_mean']):.3f}" if passes else "-",
            "cap7": f"{7 * float(capture['median']):.3f}" if capture else "-",
        }

    def budget_text(d):
        value = budget(d)
        return "-" if value is None else f"{value:.3f}"

    def under_text(d):
        value = budget(d)
        if value is None:
            return "-"
        return "yes" if value < BUDGET_MS else "no"

    out.append(md_table(
        f"4. 7-frame rollback budget (load k=7 median + 7 x re-run mean + 7 x capture median; limit {BUDGET_MS} ms)",
        headers,
        [
            row("load k=7 median", lambda d: budget_cells(d)["load7"]),
            row("7 x re-run pass mean", lambda d: budget_cells(d)["rerun7"]),
            row("7 x capture median", lambda d: budget_cells(d)["cap7"]),
            row("7-frame rollback budget", budget_text),
            row(f"under {BUDGET_MS} ms", under_text),
        ],
    ))

    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
