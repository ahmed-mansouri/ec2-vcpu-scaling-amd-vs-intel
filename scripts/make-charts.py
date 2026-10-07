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
TEXT_SCALE = 1.3      # all figures use larger type than the first draft
STROKE_SCALE = 1.5
DARK = "#1a1a1a"
# muted greys used in the first draft -> readable dark text / stronger lines
TEXT_COLOUR_MAP = {"#222": DARK, "#333": DARK, "#444": DARK, "#555": DARK, "#777": "#444"}
STROKE_COLOUR_MAP = {"#e3e3e3": "#cfcfcf", "#999": "#555", "#aaa": "#777", "#bbb": "#888", "#ccc": "#888"}
FILL_COLOUR_MAP = {"#fafafa": "#f4f4f4", "#eeeeee": "#dcdcdc", "#e9e9e9": "#d9d9d9", "#f3f7fb": "#e4eef8"}


class SVG:
    def __init__(self, w: int, h: int, scale: float = TEXT_SCALE):
        self.w, self.h = w, h
        self.scale = scale
        self.stroke_scale = STROKE_SCALE if scale != 1.0 else 1.0
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
        size = round(size * self.scale, 1)
        if self.scale != 1.0:
            fill = TEXT_COLOUR_MAP.get(fill, fill)
        tr = f" transform='rotate({rotate} {x} {y})'" if rotate else ""
        fam = f" font-family='{family}'" if family else ""
        self.add(f"<text x='{x:.1f}' y='{y:.1f}' font-size='{size}' "
                 f"text-anchor='{anchor}' font-weight='{weight}' "
                 f"fill='{fill}'{fam}{tr}>{s}</text>")

    def line(self, x1, y1, x2, y2, stroke="#333", width=1, dash=None):
        d = f" stroke-dasharray='{dash}'" if dash else ""
        if self.scale != 1.0:
            stroke = STROKE_COLOUR_MAP.get(stroke, stroke)
            width = width * self.stroke_scale
        self.add(f"<line x1='{x1:.1f}' y1='{y1:.1f}' x2='{x2:.1f}' y2='{y2:.1f}' "
                 f"stroke='{stroke}' stroke-width='{width:.2f}'{d}/>")

    def rect(self, x, y, w, h, fill="#eee", stroke="#333", width=1, rx=0,
             opacity=1.0):
        if self.scale != 1.0:
            fill = FILL_COLOUR_MAP.get(fill, fill)
            stroke = STROKE_COLOUR_MAP.get(stroke, stroke)
            if stroke != "none":
                width = width * self.stroke_scale
        self.add(f"<rect x='{x:.1f}' y='{y:.1f}' width='{w:.1f}' height='{h:.1f}' "
                 f"fill='{fill}' stroke='{stroke}' stroke-width='{width:.2f}' "
                 f"rx='{rx}' fill-opacity='{opacity}'/>")

    def circle(self, x, y, r, fill):
        r = r * (1.2 if self.scale != 1.0 else 1.0)
        self.add(f"<circle cx='{x:.1f}' cy='{y:.1f}' r='{r:.1f}' fill='{fill}' "
                 f"stroke='#fff' stroke-width='1.5'/>")

    def polyline(self, pts, stroke, width=2.5, dash=None):
        d = f" stroke-dasharray='{dash}'" if dash else ""
        p = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        width = width * (1.25 if self.scale != 1.0 else 1.0)
        self.add(f"<polyline points='{p}' fill='none' stroke='{stroke}' "
                 f"stroke-width='{width:.2f}' stroke-linejoin='round'{d}/>")

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
    W, H = 1100, 600
    L, R, T, B = 105, 40, 100, 95
    svg = SVG(W, H)
    pw, ph = W - L - R, H - T - B

    def xpos(i):
        return L + pw * (i + 0.5) / len(WORKERS)

    def ypos(v):
        return T + ph * (1 - v / ymax)

    svg.text(W / 2, 34, title, 20, weight="bold")
    if subtitle:
        for i, part in enumerate(subtitle.split("|")):
            svg.text(W / 2, 58 + i * 20, part.strip(), 12.5, fill="#555")

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
        subtitle="Mean of 5 x 60-second repetitions; whiskers show min and max repetition. | "
                 "Dashed lines = N x each instance's own single-worker mean.",
        label_offsets={("c7i.8xlarge", 32): (0, 22), ("c7i.8xlarge", 16): (0, 22),
                       ("c7i.8xlarge", 8): (0, 22), ("c7i.8xlarge", 4): (0, 22),
                       ("c7i.8xlarge", 2): (0, 22), ("c7i.8xlarge", 1): (0, 26),
                       ("c7a.8xlarge", 1): (0, -14), ("c7a.8xlarge", 16): (-40, -2),
                       ("c7a.8xlarge", 32): (-44, 6)},
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
        legend_bottom=True,
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
        subtitle="efficiency = aggregate(N) / (N x mean single-worker throughput) x 100, | "
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
    W, H = 1240, 540
    svg = SVG(W, H)
    svg.text(W / 2, 34, "What lscpu exposes: 32 vCPUs on both, but a different number of physical cores",
             18, weight="bold")

    def panel(x0, title, sub, colour, cores, tpc, l3_text, l2_text):
        pw = 580
        svg.text(x0 + pw / 2, 72, title, 15, weight="bold", fill=colour)
        svg.text(x0 + pw / 2, 92, sub, 11.5, fill="#333")
        svg.rect(x0, 104, pw, 356, "#fafafa", "#999", 1.2, rx=10)
        cols = 8
        rows = cores // cols
        cw, ch = 64, 250 / rows
        for c in range(cores):
            cx = x0 + 18 + (c % cols) * (cw + 5)
            cy = 118 + (c // cols) * (ch + 5)
            svg.rect(cx, cy, cw, ch, "#ffffff", colour, 1.4, rx=4)
            svg.text(cx + cw / 2, cy + 13, f"core {c}", 8.5, fill="#555")
            if tpc == 2:
                h2 = (ch - 24) / 2 - 1
                svg.rect(cx + 4, cy + 18, cw - 8, h2, colour, "none", opacity=0.85, rx=2)
                svg.rect(cx + 4, cy + 18 + h2 + 2, cw - 8, h2, colour, "none", opacity=0.35, rx=2)
                svg.text(cx + cw / 2, cy + 18 + h2 / 2 + 4, f"vCPU {c}", 8.5, fill="#fff", weight="bold")
                svg.text(cx + cw / 2, cy + 18 + h2 + 2 + h2 / 2 + 4, f"vCPU {c + 16}", 8.5, fill="#222", weight="bold")
            else:
                svg.rect(cx + 4, cy + 18, cw - 8, ch - 24, colour, "none", opacity=0.85, rx=2)
                svg.text(cx + cw / 2, cy + 18 + (ch - 24) / 2 + 4, f"vCPU {c}", 8.5, fill="#fff", weight="bold")
        svg.rect(x0 + 18, 388, pw - 36, 58, "#e8e8e8", "#777", 1, rx=4)
        svg.text(x0 + pw / 2, 410, l3_text, 11.5, fill="#333")
        svg.text(x0 + pw / 2, 432, l2_text, 11.5, fill="#333")

    panel(30, "Intel c7i.8xlarge", "16 physical cores x 2 SMT threads = 32 vCPUs", INSTANCES[0][2], 16, 2,
          "L3 cache: 105 MiB, 1 instance shared by all cores", "L2: 16 x 2 MiB   1 socket, 1 NUMA node")
    panel(630, "AMD c7a.8xlarge", "32 physical cores x 1 thread = 32 vCPUs", INSTANCES[1][2], 32, 1,
          "L3 cache: 128 MiB, 4 instances of 32 MiB", "L2: 32 x 1 MiB   1 socket, 1 NUMA node")

    svg.text(W / 2, 486, "Intel: vCPU n and vCPU n+16 are two hardware threads of the SAME core "
             "(lscpu -e shows CPU 16 -> CORE 0, CPU 17 -> CORE 1, ...).", 12, fill="#333")
    svg.text(W / 2, 510, "Darker = first thread of each core, lighter = its SMT sibling.   "
             "AMD: every vCPU is its own core (CPU n -> CORE n).", 12, fill="#333")
    svg.save("diagram-topology.svg")


def fig_placement():
    """Which vCPUs carry a worker at 16 and at 32 workers."""
    W, H = 1240, 600
    svg = SVG(W, H)
    svg.text(W / 2, 32, "Worker placement chosen by cpu-scale.sh", 18, weight="bold")
    svg.text(W / 2, 56, "one physical core per worker first, SMT siblings last", 13, fill="#333")

    def panel(x0, y0, title, colour, cores, tpc, workers):
        svg.text(x0 + 285, y0 - 10, title, 13.5, weight="bold", fill=colour)
        svg.rect(x0, y0, 570, 180, "#fafafa", "#999", 1, rx=8)
        cols = 16
        rows = cores // cols
        cw, ch = 32, 132 / rows
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
        svg.text(x0 + 285, y0 + 168, f"{workers} workers -> {used_cores} physical cores busy"
                 + (", 2 threads per core" if tpc == 2 and workers > 16 else ", 1 thread per core"),
                 12, fill="#333")

    panel(40, 96, "Intel c7i.8xlarge, 16 workers (vCPU 0-15)", INSTANCES[0][2], 16, 2, 16)
    panel(630, 96, "AMD c7a.8xlarge, 16 workers (vCPU 0-15)", INSTANCES[1][2], 32, 1, 16)
    panel(40, 326, "Intel c7i.8xlarge, 32 workers (vCPU 0-31)", INSTANCES[0][2], 16, 2, 32)
    panel(630, 326, "AMD c7a.8xlarge, 32 workers (vCPU 0-31)", INSTANCES[1][2], 32, 1, 32)

    svg.text(W / 2, 545, "Coloured cell = a pinned OpenSSL worker is running on that hardware thread. Grey = idle thread.",
             12.5, fill="#333")
    svg.text(W / 2, 570, "Going from 16 to 32 workers, Intel adds a second worker to each already-busy core; "
             "AMD adds 16 untouched cores.", 12.5, fill="#333")
    svg.save("diagram-worker-placement.svg")


def fig_flow():
    W, H = 1240, 340
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
    bw, bh, gap = 180, 160, 24
    x = (W - (bw * len(steps) + gap * (len(steps) - 1))) / 2
    y = 70
    for i, (title, body) in enumerate(steps):
        svg.rect(x, y, bw, bh, "#f3f7fb", "#1F6FB2", 1.4, rx=8)
        svg.text(x + bw / 2, y + 26, title, 14, weight="bold", fill="#1F6FB2")
        for j, ln in enumerate(body.split("\n")):
            svg.text(x + bw / 2, y + 62 + j * 24, ln, 12, fill="#222")
        if i < len(steps) - 1:
            svg.arrow(x + bw + 2, y + bh / 2, x + bw + gap - 2, y + bh / 2)
        x += bw + gap
    svg.text(W / 2, 266, "Every worker is  taskset -c <vCPU> openssl speed -seconds 60 -elapsed -bytes 16384 sha256",
             12, fill="#333")
    svg.text(W / 2, 290, "started in the background; the script waits for all of them before reading the logs.",
             12, fill="#333")
    svg.text(W / 2, 318, "Total wall time per instance: 6 worker counts x 5 repetitions x 60 s = 30 minutes (+ warm-up).",
             12, fill="#333")
    svg.save("diagram-test-flow.svg")


def fig_timeline(data):
    """When each worker runs, on which vCPU, over the 30-minute sweep."""
    W, H = 1300, 720
    svg = SVG(W, H)
    svg.text(W / 2, 30, "How the 30 repetitions are scheduled on the 32 vCPUs (same on both instances)",
             17, weight="bold")

    x0, y0 = 130, 92
    stage_w, rep_gap = 160, 3
    rep_w = (stage_w - 4 * rep_gap - 8) / 5
    row_h = 9
    plot_w = stage_w * len(WORKERS)
    plot_h = row_h * 32
    busy, idle = "#1F6FB2", "#e9e9e9"

    for si, n in enumerate(WORKERS):
        sx = x0 + si * stage_w
        svg.text(sx + stage_w / 2, y0 - 30, f"{n} worker{'s' if n > 1 else ''}", 12.5, weight="bold", fill="#1F6FB2")
        svg.text(sx + stage_w / 2, y0 - 12, "5 x 60 s", 10.5, fill="#555")
        for rep in range(5):
            rx = sx + 4 + rep * (rep_w + rep_gap)
            for v in range(32):
                svg.rect(rx, y0 + v * row_h, rep_w, row_h - 1, busy if v < n else idle, "none")
        if si:
            svg.line(sx, y0 - 4, sx, y0 + plot_h + 4, "#999", 1, dash="3,3")
    svg.rect(x0, y0, plot_w, plot_h, "none", "#666", 1)

    for v in (0, 8, 15, 16, 24, 31):
        dy = -4 if v == 15 else (5 if v == 16 else 0)
        svg.text(x0 - 10, y0 + v * row_h + row_h - 1 + dy, f"vCPU {v}", 10, anchor="end", fill="#333")
    svg.text(x0 - 92, y0 + plot_h / 2, "vCPU (= worker slot)", 11.5, rotate=-90, fill="#333")
    bx = x0 + plot_w + 12
    svg.line(bx, y0, bx, y0 + 16 * row_h - 1, "#444", 1.2)
    svg.line(bx, y0 + 16 * row_h, bx, y0 + plot_h, "#C0392B", 1.2)
    svg.text(bx + 9, y0 + 8 * row_h - 4, "vCPU 0-15:", 10.5, anchor="start", weight="bold", fill="#444")
    svg.text(bx + 9, y0 + 8 * row_h + 12, "one thread per", 10.5, anchor="start", fill="#444")
    svg.text(bx + 9, y0 + 8 * row_h + 28, "physical core (both)", 10.5, anchor="start", fill="#444")
    svg.text(bx + 9, y0 + 24 * row_h - 14, "vCPU 16-31:", 10.5, anchor="start", weight="bold", fill="#C0392B")
    svg.text(bx + 9, y0 + 24 * row_h + 2, "Intel = SMT siblings", 10.5, anchor="start", fill="#C0392B")
    svg.text(bx + 9, y0 + 24 * row_h + 18, "of vCPU 0-15", 10.5, anchor="start", fill="#C0392B")
    svg.text(bx + 9, y0 + 24 * row_h + 34, "AMD = 16 more cores", 10.5, anchor="start", fill="#C0392B")

    ay = y0 + plot_h + 16
    svg.line(x0, ay, x0 + plot_w, ay, "#333", 1)
    for m in range(0, 31, 5):
        tx = x0 + m / 30 * plot_w
        svg.line(tx, ay, tx, ay + 6, "#333", 1)
        svg.text(tx, ay + 22, f"{m} min", 10.5, fill="#333")
    for rep in range(5):
        rx = x0 + 4 + rep * (rep_w + rep_gap) + rep_w / 2
        svg.text(rx, ay + 40, f"rep {rep + 1}", 9, fill="#777")
    svg.text(x0 + plot_w / 2, ay + 64,
             "Time runs left to right. Each coloured column is one 60-second repetition.", 11.5, fill="#333")
    svg.text(x0 + plot_w / 2, ay + 84,
             "The coloured cells in a column are the N workers running AT THE SAME TIME, one per vCPU, lowest vCPU first.",
             11.5, fill="#333")

    agg = data["c7i.8xlarge"]["raw"][4][2]  # workers=4, repeat=3
    zy = ay + 120
    svg.text(x0, zy, "Zoom on one repetition, e.g. Intel c7i.8xlarge, workers=4, repeat=3 (minutes 12-13):",
             13, anchor="start", weight="bold")
    zx = x0
    bar_w, bar_h = 690, 26
    for v in range(4):
        by = zy + 16 + v * (bar_h + 6)
        svg.rect(zx, by, bar_w, bar_h, busy, "none", rx=3)
        svg.text(zx + 10, by + 18, f"vCPU {v}: taskset -c {v} openssl speed -seconds 60 -elapsed -bytes 16384 sha256",
                 9.5, anchor="start", fill="#fff", family="monospace")
        svg.text(zx + bar_w + 10, by + 18, "-> kB/s", 10.5, anchor="start", fill="#333")
    bottom = zy + 16 + 4 * (bar_h + 6)
    svg.text(zx + bar_w / 2, bottom + 16, "all four start together and run for the same 60 s", 10.5, fill="#555")
    sx_ = zx + bar_w + 95
    svg.arrow(sx_ - 15, zy + 16 + 2 * (bar_h + 6) - 3, sx_ + 10, zy + 16 + 2 * (bar_h + 6) - 3)
    svg.rect(sx_ + 14, zy + 14, 290, 112, "#fff8e6", "#b8860b", 1.2, rx=6)
    svg.text(sx_ + 159, zy + 38, "script waits for all 4,", 11, fill="#333")
    svg.text(sx_ + 159, zy + 58, "sums the 4 rates:", 11, fill="#333")
    svg.text(sx_ + 159, zy + 82, f"{agg:,.2f} kB/s", 12, weight="bold", fill="#333")
    svg.text(sx_ + 159, zy + 108, f"-> results.csv row 4,3,{agg:.2f}", 9.5, fill="#333", family="monospace")
    svg.text(W / 2, H - 16,
             "30 such rows per instance; the 5 rows of each worker count are averaged into summary.csv.",
             11.5, fill="#333")
    svg.save("diagram-timeline.svg")


def fig_worker(data):
    """What one worker is: one openssl process on one vCPU, hashing one cached block in a loop."""
    W, H = 1200, 600
    svg = SVG(W, H, scale=1.0)
    blue, dark, red, amber = "#1F6FB2", "#1a1a1a", "#C0392B", "#8a5a00"
    svg.text(W / 2, 34, "One worker = one 'factory'", 24, weight="bold", fill=dark)
    svg.text(W / 2, 62, "one openssl speed process, pinned to one vCPU, hashing one 16 KiB block over and over for 60 seconds",
             15, fill=dark)

    # the vCPU box
    bx, by, bw, bh = 300, 100, 600, 360
    svg.rect(bx, by, bw, bh, "#e8f1fa", blue, 3, rx=14)
    svg.text(bx + bw / 2, by + 32, "vCPU N   (pinned with  taskset -c N)", 17, weight="bold", fill=blue)

    # L1 cache with the block
    cx, cy, cw, ch = bx + 28, by + 62, 215, 150
    svg.rect(cx, cy, cw, ch, "#ffffff", dark, 2, rx=8)
    svg.text(cx + cw / 2, cy + 26, "L1 cache of this core", 15, weight="bold", fill=dark)
    svg.rect(cx + 22, cy + 44, cw - 44, 62, "#bcd4ec", blue, 2, rx=6)
    svg.text(cx + cw / 2, cy + 70, "16 KiB block", 16, weight="bold", fill=dark)
    svg.text(cx + cw / 2, cy + 92, "same bytes each time", 12, fill=dark)
    svg.text(cx + cw / 2, cy + ch - 14, "read ~110,000 times per second", 12, fill=dark)

    # SHA unit
    sx, sy, sw, sh = bx + bw - 28 - 215, cy, 215, 150
    svg.rect(sx, sy, sw, sh, "#ffffff", dark, 2, rx=8)
    svg.text(sx + sw / 2, sy + 26, "execution unit of this core", 15, weight="bold", fill=dark)
    svg.rect(sx + 22, sy + 44, sw - 44, 62, "#f6c7bf", red, 2, rx=6)
    svg.text(sx + sw / 2, sy + 70, "SHA-256", 17, weight="bold", fill=dark)
    svg.text(sx + sw / 2, sy + 92, "sha_ni instructions", 12, fill=dark)
    svg.text(sx + sw / 2, sy + sh - 14, "the only limiting resource", 12.5, weight="bold", fill=red)

    # loop arrows between them
    mid = (cx + cw + sx) / 2
    svg.line(cx + cw + 8, cy + 58, sx - 10, cy + 58, blue, 3)
    svg.arrow(sx - 24, cy + 58, sx - 8, cy + 58, blue)
    svg.text(mid, cy + 48, "block in", 14, weight="bold", fill=blue)
    svg.line(sx - 8, cy + 108, cx + cw + 10, cy + 108, blue, 3)
    svg.arrow(cx + cw + 24, cy + 108, cx + cw + 8, cy + 108, blue)
    svg.text(mid, cy + 128, "done, again", 14, weight="bold", fill=blue)
    svg.text(mid, cy + 86, "tight loop", 13, fill=dark)

    # timer + counter
    ty = by + 240
    svg.rect(bx + 28, ty, 262, 78, "#ffffff", dark, 2, rx=8)
    svg.text(bx + 159, ty + 30, "timer: 60 seconds", 16, weight="bold", fill=dark)
    svg.text(bx + 159, ty + 56, "wall-clock time  (-elapsed)", 12.5, fill=dark)
    svg.rect(bx + bw - 28 - 262, ty, 262, 78, "#ffffff", dark, 2, rx=8)
    svg.text(bx + bw - 159, ty + 30, "counter: hashes finished", 16, weight="bold", fill=dark)
    svg.text(bx + bw - 159, ty + 56, "+1 per completed 16 KiB hash", 12.5, fill=dark)

    # output
    ox, oy, ow, oh = bx + bw + 70, by + 80, 220, 200
    svg.line(bx + bw + 4, by + bh / 2, ox - 14, by + bh / 2, dark, 3)
    svg.arrow(ox - 30, by + bh / 2, ox - 6, by + bh / 2, dark)
    svg.rect(ox, oy, ow, oh, "#fff2cc", amber, 2.5, rx=8)
    svg.text(ox + ow / 2, oy + 28, "reported after 60 s", 14, weight="bold", fill=dark)
    svg.text(ox + ow / 2, oy + 58, "counter x 16,384", 15, family="monospace", fill=dark)
    svg.text(ox + ow / 2, oy + 80, "-----------------", 15, family="monospace", fill=dark)
    svg.text(ox + ow / 2, oy + 102, "60 seconds", 15, family="monospace", fill=dark)
    svg.text(ox + ow / 2, oy + 134, "= bytes per second", 15, weight="bold", fill=dark)
    one = data["c7a.8xlarge"]["summary"][1]["agg"]
    svg.text(ox + ow / 2, oy + 162, f"e.g. {one:,.0f} kB/s", 13.5, family="monospace", fill=dark)
    svg.text(ox + ow / 2, oy + 184, f"= {one / 1e6:.2f} GB/s, worker alone", 12.5, fill=dark)
    svg.text(ox + ow / 2, oy + oh + 30, "This number is the worker's", 14, fill=dark)
    svg.text(ox + ow / 2, oy + oh + 54, "THROUGHPUT", 18, weight="bold", fill=amber)

    # things deliberately NOT involved, on the left
    nx, nw = 40, 190
    svg.text(nx + nw / 2, by + 24, "NOT involved", 16, weight="bold", fill=dark)
    for i, label in enumerate(("disk", "network", "main memory (RAM)", "other workers")):
        yy = by + 50 + i * 76
        svg.rect(nx, yy, nw, 52, "#f0f0f0", "#666", 1.8, rx=8)
        svg.text(nx + nw / 2, yy + 33, label, 15, fill=dark)
        svg.line(nx + nw + 6, yy + 26, bx - 10, yy + 26, "#888", 2, dash="6,5")
        svg.line(bx - 32, yy + 14, bx - 8, yy + 38, red, 3.5)
        svg.line(bx - 32, yy + 38, bx - 8, yy + 14, red, 3.5)

    svg.text(W / 2, H - 100, "N workers = N copies of this, each on its own vCPU, all started at the same instant.",
             15, fill=dark)
    svg.text(W / 2, H - 74, "They never talk to each other. Aggregate throughput = the sum of the N reported numbers.",
             15, fill=dark)
    svg.rect(60, H - 52, W - 120, 36, "#fde8e4", red, 1.5, rx=8)
    svg.text(W / 2, H - 28, "Nothing outside the core is used, so a worker can only slow down if its core is shared "
             "with another worker (SMT) or runs at a lower clock.", 14, weight="bold", fill=red)
    svg.save("diagram-one-worker.svg")


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
    fig_timeline(data)
    fig_worker(data)

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
