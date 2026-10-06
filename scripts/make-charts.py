#!/usr/bin/env python3
"""
make-charts.py

Reads results/<instance>/results.csv for both instances, recomputes the
summary (average aggregate, average per-worker, scaling efficiency),
verifies that it matches results/<instance>/summary.csv produced on the
instance, and renders every figure used by README.md as SVG under images/.

Only the Python standard library is used, so this runs on any machine.

Usage:
    python3 scripts/make-charts.py
"""
from __future__ import annotations

import csv
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
IMAGES = ROOT / "images"

INSTANCES = [
    # key, label, colour, physical cores, threads per core
    ("c7i.8xlarge", "Intel c7i.8xlarge (Xeon Platinum 8488C)", "#1F6FB2", 16, 2),
    ("c7a.8xlarge", "AMD c7a.8xlarge (EPYC 9R14)", "#D7301F", 32, 1),
]
WORKERS = [1, 2, 4, 8, 16, 32]
FONT = "font-family='Segoe UI, Helvetica, Arial, sans-serif'"


# --------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------
def load(instance: str) -> dict:
    raw: dict[int, list[float]] = {w: [] for w in WORKERS}
    with open(RESULTS / instance / "results.csv", newline="") as fh:
        for row in csv.DictReader(fh):
            raw[int(row["workers"])].append(float(row["aggregate_kBps"]))

    baseline = statistics.mean(raw[1])
    summary = {}
    for w in WORKERS:
        agg = statistics.mean(raw[w])
        summary[w] = {
            "n": len(raw[w]),
            "agg": agg,
            "per_worker": agg / w,
            "eff": 100.0 * agg / (w * baseline),
            "agg_min": min(raw[w]),
            "agg_max": max(raw[w]),
            "eff_min": 100.0 * min(raw[w]) / (w * baseline),
            "eff_max": 100.0 * max(raw[w]) / (w * baseline),
        }

    # Verify against the summary.csv written on the instance.
    with open(RESULTS / instance / "summary.csv", newline="") as fh:
        for row in csv.DictReader(fh):
            w = int(row["workers"])
            for col, key in (("avg_aggregate_kBps", "agg"),
                             ("avg_per_worker_kBps", "per_worker"),
                             ("scaling_efficiency_pct", "eff")):
                expected = float(row[col])
                got = summary[w][key]
                if abs(expected - got) > 0.006:
                    sys.exit(f"MISMATCH {instance} workers={w} {col}: "
                             f"instance wrote {expected}, recomputed {got:.2f}")
    return {"raw": raw, "summary": summary, "baseline": baseline}


# --------------------------------------------------------------------------
# SVG helpers
# --------------------------------------------------------------------------
class SVG:
    def __init__(self, w: int, h: int):
        self.w, self.h = w, h
        self.parts = [
            f"<svg xmlns='http://www.w3.org/2000/svg' width='{w}' height='{h}' "
            f"viewBox='0 0 {w} {h}' {FONT}>",
            f"<rect width='{w}' height='{h}' fill='#ffffff'/>",
        ]

    def add(self, s: str) -> None:
        self.parts.append(s)

    def text(self, x, y, s, size=13, anchor="middle", weight="normal",
             fill="#222", rotate=None, family=None):
        s = (str(s).replace("&", "&amp;").replace("<", "&lt;")
             .replace(">", "&gt;"))
        tr = f" transform='rotate({rotate} {x} {y})'" if rotate else ""
        fam = f" font-family='{family}'" if family else ""
        self.add(f"<text x='{x:.1f}' y='{y:.1f}' font-size='{size}' "
                 f"text-anchor='{anchor}' font-weight='{weight}' "
                 f"fill='{fill}'{fam}{tr}>{s}</text>")

    def line(self, x1, y1, x2, y2, stroke="#333", width=1, dash=None):
        d = f" stroke-dasharray='{dash}'" if dash else ""
        self.add(f"<line x1='{x1:.1f}' y1='{y1:.1f}' x2='{x2:.1f}' y2='{y2:.1f}' "
                 f"stroke='{stroke}' stroke-width='{width}'{d}/>")

    def rect(self, x, y, w, h, fill="#eee", stroke="#333", width=1, rx=0,
             opacity=1.0):
        self.add(f"<rect x='{x:.1f}' y='{y:.1f}' width='{w:.1f}' height='{h:.1f}' "
                 f"fill='{fill}' stroke='{stroke}' stroke-width='{width}' "
                 f"rx='{rx}' fill-opacity='{opacity}'/>")

    def circle(self, x, y, r, fill):
        self.add(f"<circle cx='{x:.1f}' cy='{y:.1f}' r='{r}' fill='{fill}' "
                 f"stroke='#fff' stroke-width='1.5'/>")

    def polyline(self, pts, stroke, width=2.5, dash=None):
        d = f" stroke-dasharray='{dash}'" if dash else ""
        p = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        self.add(f"<polyline points='{p}' fill='none' stroke='{stroke}' "
                 f"stroke-width='{width}' stroke-linejoin='round'{d}/>")

    def arrow(self, x1, y1, x2, y2, stroke="#444"):
        self.line(x1, y1, x2, y2, stroke, 1.8)
        import math
        ang = math.atan2(y2 - y1, x2 - x1)
        for s in (+1, -1):
            a = ang + s * 2.6
            self.line(x2, y2, x2 + 9 * math.cos(a), y2 + 9 * math.sin(a),
                      stroke, 1.8)

    def save(self, name: str) -> None:
        self.add("</svg>")
        (IMAGES / name).write_text("\n".join(self.parts) + "\n")
        print(f"wrote images/{name}")


def fmt_num(v: float) -> str:
    return f"{v:,.0f}"


# --------------------------------------------------------------------------
# Generic line chart over the worker counts
# --------------------------------------------------------------------------
def line_chart(name, title, ylabel, series, ymax, ytick, value_fmt,
               ref_lines=(), whiskers=None, subtitle=None, label_offsets=None,
               legend_bottom=False):
    W, H = 960, 560
    L, R, T, B = 95, 40, 80, 90
    svg = SVG(W, H)
    pw, ph = W - L - R, H - T - B

    def xpos(i):
        return L + pw * (i + 0.5) / len(WORKERS)

    def ypos(v):
        return T + ph * (1 - v / ymax)

    svg.text(W / 2, 34, title, 20, weight="bold")
    if subtitle:
        svg.text(W / 2, 58, subtitle, 13, fill="#555")

    # grid and axes
    v = 0.0
    while v <= ymax + 1e-9:
        y = ypos(v)
        svg.line(L, y, L + pw, y, "#e3e3e3")
        svg.text(L - 10, y + 4, value_fmt(v), 12, anchor="end", fill="#444")
        v += ytick
    svg.line(L, T, L, T + ph, "#333", 1.2)
    svg.line(L, T + ph, L + pw, T + ph, "#333", 1.2)
    for i, w in enumerate(WORKERS):
        svg.text(xpos(i), T + ph + 22, str(w), 13, fill="#222")
    svg.text(L + pw / 2, T + ph + 48, "Concurrent pinned workers (one OpenSSL process per vCPU)",
             13, fill="#333")
    svg.text(28, T + ph / 2, ylabel, 13, rotate=-90, fill="#333")

    for label, y, colour in ref_lines:
        svg.line(L, ypos(y), L + pw, ypos(y), colour, 1.4, dash="7,5")

    # series
    for s in series:
        pts = [(xpos(i), ypos(val)) for i, val in enumerate(s["values"])]
        svg.polyline(pts, s["colour"], 3 if not s.get("dash") else 2,
                     dash=s.get("dash"))
        if whiskers and s["key"] in whiskers:
            for i, (lo, hi) in enumerate(whiskers[s["key"]]):
                x = xpos(i)
                svg.line(x, ypos(lo), x, ypos(hi), s["colour"], 1.5)
                svg.line(x - 5, ypos(lo), x + 5, ypos(lo), s["colour"], 1.5)
                svg.line(x - 5, ypos(hi), x + 5, ypos(hi), s["colour"], 1.5)
        if not s.get("dash"):
            for i, (x, y) in enumerate(pts):
                svg.circle(x, y, 5, s["colour"])
                off = (label_offsets or {}).get((s["key"], WORKERS[i]), (0, -12))
                svg.text(x + off[0], y + off[1], s["label_fmt"](s["values"][i]),
                         11.5, fill=s["colour"], weight="bold")

    # legend
    entries = list(series) + [{"name": lbl, "colour": c, "dash": "7,5"}
                              for lbl, _, c in ref_lines]
    lx = L + 14
    ly = (T + ph - 22 * len(entries) - 6) if legend_bottom else T + 14
    for s in entries:
        svg.line(lx, ly, lx + 34, ly, s["colour"], 3, dash=s.get("dash"))
        if not s.get("dash"):
            svg.circle(lx + 17, ly, 4.5, s["colour"])
        svg.text(lx + 42, ly + 4, s["name"], 12.5, anchor="start")
        ly += 22
    svg.save(name)


# --------------------------------------------------------------------------
# Figures
# --------------------------------------------------------------------------
def fig_aggregate(data):
    series, whisk = [], {}
    for key, label, colour, _, _ in INSTANCES:
        s = data[key]["summary"]
        series.append({
            "key": key, "name": label, "colour": colour,
            "values": [s[w]["agg"] / 1e6 for w in WORKERS],
            "label_fmt": lambda v: f"{v:.2f}",
        })
        whisk[key] = [(s[w]["agg_min"] / 1e6, s[w]["agg_max"] / 1e6) for w in WORKERS]
    # perfect-scaling reference from each instance's own 1-worker baseline
    for key, label, colour, _, _ in INSTANCES:
        b = data[key]["baseline"] / 1e6
        series.append({
            "key": key + "-ideal", "name": f"Perfect linear scaling from {key.split('.')[0]} 1-worker baseline",
            "colour": colour, "dash": "6,6", "values": [b * w for w in WORKERS],
            "label_fmt": lambda v: "",
        })
    line_chart(
        "chart-aggregate-throughput.svg",
        "Aggregate SHA-256 throughput versus number of pinned workers",
        "Aggregate throughput (GB/s, decimal, sum of all workers)",
        series, 64, 8, lambda v: f"{v:.0f}",
        whiskers=whisk,
        subtitle="Mean of 5 x 60-second repetitions; whiskers show min and max repetition. "
                 "Dashed lines = N x each instance's own single-worker mean.",
        label_offsets={("c7i.8xlarge", 32): (0, 22), ("c7i.8xlarge", 16): (0, 22),
                       ("c7i.8xlarge", 8): (0, 22), ("c7i.8xlarge", 4): (0, 22),
                       ("c7i.8xlarge", 2): (0, 22), ("c7i.8xlarge", 1): (-34, 4),
                       ("c7a.8xlarge", 1): (0, -12)},
    )


def fig_per_worker(data):
    series = []
    for key, label, colour, _, _ in INSTANCES:
        s = data[key]["summary"]
        series.append({
            "key": key, "name": label, "colour": colour,
            "values": [s[w]["per_worker"] / 1e3 for w in WORKERS],
            "label_fmt": lambda v: f"{v:,.0f}",
        })
    line_chart(
        "chart-per-worker-throughput.svg",
        "Average throughput of ONE worker as more workers are added",
        "Per-worker throughput (MB/s, decimal)",
        series, 2000, 250, lambda v: f"{v:,.0f}",
        subtitle="aggregate / N. A flat line means every added worker got a full core's worth of work done.",
        label_offsets={("c7i.8xlarge", w): (0, 22) for w in WORKERS},
    )


def fig_efficiency(data):
    series, whisk = [], {}
    for key, label, colour, _, _ in INSTANCES:
        s = data[key]["summary"]
        series.append({
            "key": key, "name": label, "colour": colour,
            "values": [s[w]["eff"] for w in WORKERS],
            "label_fmt": lambda v: f"{v:.2f}%",
        })
        whisk[key] = [(s[w]["eff_min"], s[w]["eff_max"]) for w in WORKERS]
    line_chart(
        "chart-scaling-efficiency.svg",
        "Useful-throughput scaling efficiency (not CPU utilisation)",
        "Scaling efficiency (%)",
        series, 120, 20, lambda v: f"{v:.0f}%",
        ref_lines=[("100% = perfect linear scaling", 100, "#2e7d32")],
        whiskers=whisk,
        subtitle="efficiency = aggregate(N) / (N x mean single-worker throughput) x 100, "
                 "each instance against its own baseline",
        label_offsets={("c7i.8xlarge", w): (0, 24) for w in WORKERS},
        legend_bottom=True,
    )


def fig_16_vs_32(data):
    W, H = 960, 520
    svg = SVG(W, H)
    svg.text(W / 2, 34, "The decisive step: 16 -> 32 workers", 20, weight="bold")
    svg.text(W / 2, 58, "Both instances double the worker count. Only AMD doubles the number of physical cores in use.",
             13, fill="#555")
    L, T, ph = 110, 95, 300
    ymax = 64.0
    def ypos(v): return T + ph * (1 - v / ymax)
    for v in range(0, 65, 8):
        svg.line(L, ypos(v), W - 40, ypos(v), "#e3e3e3")
        svg.text(L - 10, ypos(v) + 4, f"{v}", 12, anchor="end", fill="#444")
    svg.line(L, T, L, T + ph, "#333", 1.2)
    svg.line(L, T + ph, W - 40, T + ph, "#333", 1.2)
    svg.text(28, T + ph / 2, "Aggregate throughput (GB/s)", 13, rotate=-90, fill="#333")

    groups = [(key, label, colour) for key, label, colour, _, _ in INSTANCES]
    gw = (W - 40 - L) / len(groups)
    bw = 110
    for gi, (key, label, colour) in enumerate(groups):
        s = data[key]["summary"]
        gx = L + gw * gi + gw / 2
        a16, a32 = s[16]["agg"] / 1e6, s[32]["agg"] / 1e6
        x16, x32 = gx - bw - 12, gx + 12
        svg.rect(x16, ypos(a16), bw, T + ph - ypos(a16), colour, "none", opacity=0.55)
        svg.rect(x32, ypos(a32), bw, T + ph - ypos(a32), colour, "none")
        svg.text(x16 + bw / 2, ypos(a16) - 8, f"{a16:.2f}", 13, weight="bold", fill="#222")
        svg.text(x32 + bw / 2, ypos(a32) - 8, f"{a32:.2f}", 13, weight="bold", fill="#222")
        svg.text(x16 + bw / 2, T + ph + 20, "16 workers", 12.5)
        svg.text(x32 + bw / 2, T + ph + 20, "32 workers", 12.5)
        svg.text(gx, T + ph + 42, label, 13, weight="bold", fill=colour)
        gain = (a32 / a16 - 1) * 100
        drop = (1 - s[32]["per_worker"] / s[16]["per_worker"]) * 100
        pc16 = min(16, INSTANCES[gi][3]); pc32 = min(32, INSTANCES[gi][3])
        svg.text(gx, T + ph + 66, f"physical cores in use: {pc16} -> {pc32}", 12.5, fill="#333")
        svg.text(gx, T + ph + 86, f"aggregate: +{gain:.2f}%    per-worker: -{drop:.2f}%", 12.5, fill="#333")
        # arrow 16 -> 32
        svg.arrow(x16 + bw, ypos(a16) - 30, x32, ypos(a32) - 30, "#555")
    svg.save("chart-16-vs-32.svg")


def fig_topology():
    """Side-by-side picture of what the guest sees on each instance."""
    W, H = 1000, 470
    svg = SVG(W, H)
    svg.text(W / 2, 32, "What lscpu exposes: 32 vCPUs on both, but a different number of physical cores",
             18, weight="bold")

    def panel(x0, title, colour, cores, tpc, l3_text):
        svg.text(x0 + 225, 68, title, 15, weight="bold", fill=colour)
        svg.rect(x0, 80, 450, 320, "#fafafa", "#999", 1.2, rx=10)
        cols = 8
        rows = cores // cols
        cw, ch = 50, 250 / rows
        for c in range(cores):
            cx = x0 + 15 + (c % cols) * (cw + 4)
            cy = 95 + (c // cols) * (ch + 4)
            svg.rect(cx, cy, cw, ch, "#ffffff", colour, 1.4, rx=4)
            svg.text(cx + cw / 2, cy + 12, f"core {c}", 9, fill="#555")
            if tpc == 2:
                svg.rect(cx + 4, cy + 17, cw - 8, (ch - 24) / 2 - 1, colour, "none", opacity=0.75, rx=2)
                svg.rect(cx + 4, cy + 17 + (ch - 24) / 2 + 1, cw - 8, (ch - 24) / 2 - 1, colour, "none", opacity=0.35, rx=2)
                svg.text(cx + cw / 2, cy + 17 + (ch - 24) / 4 + 4, f"vCPU {c}", 9, fill="#fff", weight="bold")
                svg.text(cx + cw / 2, cy + 17 + 3 * (ch - 24) / 4 + 5, f"vCPU {c + 16}", 9, fill="#222", weight="bold")
            else:
                svg.rect(cx + 4, cy + 17, cw - 8, ch - 24, colour, "none", opacity=0.75, rx=2)
                svg.text(cx + cw / 2, cy + 17 + (ch - 24) / 2 + 4, f"vCPU {c}", 9, fill="#fff", weight="bold")
        svg.rect(x0 + 15, 355, 420, 34, "#e8e8e8", "#777", 1, rx=4)
        svg.text(x0 + 225, 377, l3_text, 12, fill="#333")

    panel(40, "Intel c7i.8xlarge: 16 physical cores x 2 SMT threads", INSTANCES[0][2], 16, 2,
          "L3 cache: 105 MiB (1 instance)   L2: 16 x 2 MiB   1 socket, 1 NUMA node")
    panel(510, "AMD c7a.8xlarge: 32 physical cores x 1 thread", INSTANCES[1][2], 32, 1,
          "L3 cache: 128 MiB (4 instances)   L2: 32 x 1 MiB   1 socket, 1 NUMA node")

    svg.text(W / 2, 425, "Intel: vCPU n and vCPU n+16 are two hardware threads of the SAME core "
             "(lscpu -e shows CPU 16 -> CORE 0, CPU 17 -> CORE 1, ...).", 12.5, fill="#333")
    svg.text(W / 2, 447, "AMD: every vCPU is its own core (CPU n -> CORE n). "
             "Darker = first thread of each core, lighter = SMT sibling.", 12.5, fill="#333")
    svg.save("diagram-topology.svg")


def fig_placement():
    """Which vCPUs carry a worker at 16 and at 32 workers."""
    W, H = 1000, 560
    svg = SVG(W, H)
    svg.text(W / 2, 32, "Worker placement chosen by cpu-scale.sh (one physical core per worker first, SMT siblings last)",
             17, weight="bold")

    def panel(x0, y0, title, colour, cores, tpc, workers):
        svg.text(x0 + 225, y0 - 8, title, 13.5, weight="bold", fill=colour)
        svg.rect(x0, y0, 450, 170, "#fafafa", "#999", 1, rx=8)
        cols = 16
        rows = cores // cols
        cw, ch = 25, 130 / rows
        busy_vcpus = set(range(workers)) if tpc == 1 else (
            set(range(min(workers, 16))) | set(range(16, 16 + max(0, workers - 16))))
        for c in range(cores):
            cx = x0 + 12 + (c % cols) * (cw + 2)
            cy = y0 + 12 + (c // cols) * (ch + 6)
            svg.rect(cx, cy, cw, ch, "#fff", "#aaa", 1, rx=3)
            if tpc == 2:
                for t, vc in enumerate((c, c + 16)):
                    ty = cy + 3 + t * (ch - 6) / 2
                    busy = vc in busy_vcpus
                    svg.rect(cx + 3, ty, cw - 6, (ch - 6) / 2 - 2,
                             colour if busy else "#eeeeee", "none", rx=2)
            else:
                busy = c in busy_vcpus
                svg.rect(cx + 3, cy + 3, cw - 6, ch - 6, colour if busy else "#eeeeee", "none", rx=2)
        used_cores = min(workers, cores)
        svg.text(x0 + 225, y0 + 160, f"{workers} workers -> {used_cores} physical cores busy"
                 + (", 2 threads per core" if tpc == 2 and workers > 16 else ", 1 thread per core"),
                 12, fill="#333")

    panel(40, 70, "Intel c7i.8xlarge, 16 workers (vCPU 0-15)", INSTANCES[0][2], 16, 2, 16)
    panel(510, 70, "AMD c7a.8xlarge, 16 workers (vCPU 0-15)", INSTANCES[1][2], 32, 1, 16)
    panel(40, 300, "Intel c7i.8xlarge, 32 workers (vCPU 0-31)", INSTANCES[0][2], 16, 2, 32)
    panel(510, 300, "AMD c7a.8xlarge, 32 workers (vCPU 0-31)", INSTANCES[1][2], 32, 1, 32)

    svg.text(W / 2, 505, "Coloured cell = a pinned OpenSSL worker is running on that hardware thread. Grey = idle thread.",
             12.5, fill="#333")
    svg.text(W / 2, 527, "Going from 16 to 32 workers, Intel adds a second worker to each already-busy core; "
             "AMD adds 16 untouched cores.", 12.5, fill="#333")
    svg.save("diagram-worker-placement.svg")


def fig_flow():
    W, H = 1000, 300
    svg = SVG(W, H)
    svg.text(W / 2, 30, "Test procedure (identical on both instances, run at the same time)", 17, weight="bold")
    steps = [
        ("1. Launch", "c7i.8xlarge and\nc7a.8xlarge\nsame AMI, same AZ"),
        ("2. Verify", "IMDSv2 instance-type\nlscpu topology\nopenssl version"),
        ("3. Warm-up", "10 s openssl speed\non one vCPU\n(discarded)"),
        ("4. Sweep", "N = 1,2,4,8,16,32\n5 repetitions each\n60 s per repetition"),
        ("5. Measure", "sum of per-worker\nkB/s -> results.csv\n(one row per rep)"),
        ("6. Summarise", "mean, per-worker,\nefficiency vs own\n1-worker baseline"),
    ]
    bw, bh, gap = 140, 150, 22
    x = (W - (bw * len(steps) + gap * (len(steps) - 1))) / 2
    y = 70
    for i, (title, body) in enumerate(steps):
        svg.rect(x, y, bw, bh, "#f3f7fb", "#1F6FB2", 1.4, rx=8)
        svg.text(x + bw / 2, y + 26, title, 14, weight="bold", fill="#1F6FB2")
        for j, ln in enumerate(body.split("\n")):
            svg.text(x + bw / 2, y + 58 + j * 20, ln, 12, fill="#222")
        if i < len(steps) - 1:
            svg.arrow(x + bw + 2, y + bh / 2, x + bw + gap - 2, y + bh / 2)
        x += bw + gap
    svg.text(W / 2, 255, "Every worker is 'taskset -c <vCPU> openssl speed -seconds 60 -elapsed -bytes 16384 sha256', "
             "started in the background; the script waits for all of them before reading the logs.",
             12, fill="#333")
    svg.text(W / 2, 277, "Total wall time per instance: 6 worker counts x 5 repetitions x 60 s = 30 minutes (+ warm-up).",
             12, fill="#333")
    svg.save("diagram-test-flow.svg")


def main() -> None:
    IMAGES.mkdir(exist_ok=True)
    data = {key: load(key) for key, *_ in INSTANCES}
    print("summary.csv recomputed from results.csv and verified for both instances")
    fig_aggregate(data)
    fig_per_worker(data)
    fig_efficiency(data)
    fig_16_vs_32(data)
    fig_topology()
    fig_placement()
    fig_flow()

    # Print derived numbers used in README so they can be checked.
    i, a = data["c7i.8xlarge"]["summary"], data["c7a.8xlarge"]["summary"]
    print(f"AMD/Intel aggregate at 32:      +{(a[32]['agg']/i[32]['agg']-1)*100:.2f}%")
    print(f"Intel/AMD aggregate at 32:      -{(1-i[32]['agg']/a[32]['agg'])*100:.2f}%")
    print(f"Intel 16->32 aggregate gain:    +{(i[32]['agg']/i[16]['agg']-1)*100:.2f}%")
    print(f"AMD   16->32 aggregate gain:    +{(a[32]['agg']/a[16]['agg']-1)*100:.2f}%")
    print(f"Intel 16->32 per-worker change: {(i[32]['per_worker']/i[16]['per_worker']-1)*100:.2f}%")
    print(f"AMD   16->32 per-worker change: {(a[32]['per_worker']/a[16]['per_worker']-1)*100:.2f}%")
    print(f"AMD/Intel aggregate at 16:      +{(a[16]['agg']/i[16]['agg']-1)*100:.2f}%")
    print(f"AMD/Intel aggregate at 1:       +{(a[1]['agg']/i[1]['agg']-1)*100:.2f}%")
    for key in ("c7i.8xlarge", "c7a.8xlarge"):
        s = data[key]["summary"]
        for w in WORKERS:
            spread = (s[w]["agg_max"] - s[w]["agg_min"]) / s[w]["agg"] * 100
            print(f"{key} workers={w:2d} n={s[w]['n']} min-max spread {spread:.2f}% of mean")


if __name__ == "__main__":
    main()
