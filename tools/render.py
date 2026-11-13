"""Renders the dithered images for the profile README.

    python tools/render.py usage  OUT_DIR   # token and cost charts
    python tools/render.py static OUT_DIR   # composer header and social buttons (run once, commit)

The dither follows t3+ (github.com/alextyhwang/t3plus): Bayer ordered dither,
2 px cells everywhere (images are 840 px wide, the README column is 846 px, so
they show 1:1), the composer glow from ditherMath.js, the chart fill from
ditherChart.js and the button tiles from botArt.js. Text is drawn as Geist
outlines (tools/fonts, SIL OFL), so no font has to load on GitHub.

Usage data comes from T3 Code's local `t3plus-home.json` feed when `--feed` is
provided. Only daily provider totals are used. Without a feed, the public
activity API remains a safe fallback for manual/Actions renders.
Needs Python 3.10+ and fonttools.
"""
import colorsys
import json
import math
import pathlib
import sys
from collections import defaultdict
from datetime import date, timedelta

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

FONT_DIR = pathlib.Path(__file__).parent / "fonts"
GEIST = {w: str(FONT_DIR / f"Geist-{w}.ttf") for w in ("Regular", "Medium")}
GEIST_MONO = str(FONT_DIR / "GeistMono-Regular.ttf")


W = 840


CELL = 2


THEMES = {
    "dark": dict(fg="#e6edf3", muted="#9198a1", faint="#ffffff", faint_a=0.08, border="#3d444d", card="#151b23",
                 codex="#f0f6fc", claude="#d97757", accent=(79, 140, 247), bg="#0d1117"),
    "light": dict(fg="#1f2328", muted="#59636e", faint="#1f2328", faint_a=0.07, border="#d1d9e0", card="#f6f8fa",
                  codex="#1f2328", claude="#d97757", accent=(37, 99, 235), bg="#ffffff"),
}


# The order and names follow T3 Code's Usage page. Unknown providers are kept
# and receive a stable neutral color so a newly added provider is never lost.
PROVIDERS = {
    "codex": ("Codex", "#f0f6fc", "#1f2328"),
    "claude": ("Claude Code", "#d97757", "#d97757"),
    "grok": ("Grok Build", "#a8adb5", "#59636e"),
    "cursor": ("Cursor", "#8b8b8b", "#59636e"),
    "antigravity": ("Antigravity", "#8c7bd1", "#6b5bb5"),
    "opencode": ("OpenCode", "#5b9bbd", "#3e718d"),
    "pi": ("Pi", "#4d9f8a", "#34705f"),
}
PROVIDER_ORDER = ["codex", "claude", "grok", "cursor", "antigravity", "opencode", "pi"]
UNKNOWN_COLORS = [("#b8c0cc", "#59636e"), ("#d69e62", "#a66d32"), ("#8eb4a5", "#4e7768")]


def bayer(n):
    m = [[0]]
    while len(m) < n:
        s = len(m)
        nx = [[0] * (2 * s) for _ in range(2 * s)]
        for y in range(s):
            for x in range(s):
                v = m[y][x] * 4
                nx[y][x], nx[y][x + s], nx[y + s][x], nx[y + s][x + s] = v, v + 2, v + 3, v + 1
        m = nx
    return m


B16 = bayer(16)


B8 = [[0, 48, 12, 60, 3, 51, 15, 63], [32, 16, 44, 28, 35, 19, 47, 31], [8, 56, 4, 52, 11, 59, 7, 55],
      [40, 24, 36, 20, 43, 27, 39, 23], [2, 50, 14, 62, 1, 49, 13, 61], [34, 18, 46, 30, 33, 17, 45, 29],
      [10, 58, 6, 54, 9, 57, 5, 53], [42, 26, 38, 22, 41, 25, 37, 21]]


def thr(x, y):
    return (B16[y & 15][x & 15] + 0.5) / 256


def dither_level(v, levels, t):
    scaled = max(0, min(1, v)) * (levels - 1)
    lo = math.floor(scaled)
    return min(levels - 1, lo + 1 if scaled - lo > t else lo)


GLOW = dict(coreRx=0.288, coreRy=0.216, haloRx=0.45, haloRy=0.396, drop=0.05)


def glow_strength(u, v, cx, intensity, cy=1 + GLOW["drop"], sx=1.0, sy=1.0):
    du, dv = (u - cx) / sx, (v - cy) / sy
    d1 = math.hypot(du / GLOW["coreRx"], dv / GLOW["coreRy"])
    d2 = math.hypot(du / GLOW["haloRx"], dv / GLOW["haloRy"])
    if d2 >= 1 and d1 >= 1:
        return 0
    core = (1 - d1) ** 1.2 if d1 < 1 else 0
    halo = (1 - d2) ** 1.6 * 0.7 if d2 < 1 else 0
    return min(1, (1 - (1 - core) * (1 - halo)) * (0.6 + 0.8 * intensity))


def shade(rgb, l):
    h, _, s = colorsys.rgb_to_hls(*[c / 255 for c in rgb])
    return tuple(round(c * 255) for c in colorsys.hls_to_rgb(h, l, max(s, 0.35)))


def glow_tones(rgb, theme):
    _, l, _ = colorsys.rgb_to_hls(*[c / 255 for c in rgb])
    base = min(0.62, max(0.45, l))
    if theme == "dark":  # t3+ glowTones("bayer"): deep -> accent -> hot
        return [None, (shade(rgb, base * 0.45), 0.7), (shade(rgb, base * 0.75), 0.88), (rgb, 1), (shade(rgb, min(0.88, base + 0.25)), 1)]
    # Light mode inverts the lightness ramp: pale at the rim, deep in the core.
    return [None, (shade(rgb, 0.86), 0.8), (shade(rgb, 0.72), 0.9), (rgb, 1), (shade(rgb, 0.36), 1)]


def dither_density(d):
    d = max(0, min(1, d))
    return 0.02 + 0.98 * (1 - d) ** 1.8


def dither_on(c, r, density):
    return (B8[r & 7][c & 7] + 0.5) / 64 < density


def edge_at(points, x):
    if len(points) < 2 or x < points[0][0] or x > points[-1][0]:
        return None
    i = 1
    while i < len(points) - 1 and points[i][0] < x:
        i += 1
    (x0, y0), (x1, y1) = points[i - 1], points[i]
    return y1 if x1 == x0 else y0 + (x - x0) / (x1 - x0) * (y1 - y0)


def dither_cells(cols, rows, series):
    """Port of ditherChart.js ditherCells: {(c, r): (series, is_edge)}."""
    fill = [-1] * (cols * rows)
    edge = [-1] * (cols * rows)
    for si, s in enumerate(series):
        prev = None
        for c in range(cols):
            y = edge_at(s["points"], (c + 0.5) / cols)
            if y is None:
                prev = None
                continue
            top = max(0, min(rows - 1, math.floor(y * rows)))
            lo = top if prev is None else min(top, prev + (1 if prev < top else 0))
            hi = top if prev is None else max(top, prev - (1 if prev > top else 0))
            prev = top
            for r in range(lo, hi + 1):
                edge[r * cols + c] = si
            for r in range(top + 1, rows):
                if dither_on(c + si * 4, r, dither_density((r - top) / max(1, rows - top))):
                    fill[r * cols + c] = si
    return fill, edge


def n(v):
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return s if s not in ("-0", "") else "0"


def hexc(c):
    return c if isinstance(c, str) else "#%02x%02x%02x" % c


def cells_path(cells, cw, ch=None, ox=0, oy=0):
    """Cells (col, row) -> one path, merging horizontal runs."""
    ch = ch or cw
    rows = defaultdict(list)
    for x, y in cells:
        rows[y].append(x)
    out = []
    for y in sorted(rows):
        xs = sorted(rows[y])
        i = 0
        while i < len(xs):
            j = i
            while j + 1 < len(xs) and xs[j + 1] == xs[j] + 1:
                j += 1
            run = (j - i + 1) * cw
            out.append(f"M{n(ox + xs[i] * cw)} {n(oy + y * ch)}h{n(run)}v{n(ch)}h-{n(run)}z")
            i = j + 1
    return "".join(out)


_fonts = {}


def text_glyphs(text, font_file, size, x, y, anchor="start", tracking=0.0):
    """Text as vector outlines (no font loading on GitHub). Returns ([(x, d)], width)."""
    f = _fonts.setdefault(font_file, TTFont(font_file))
    gs, cmap, upm, hmtx = f.getGlyphSet(), f.getBestCmap(), f["head"].unitsPerEm, f["hmtx"]
    k = size / upm
    names = [cmap.get(ord(ch), cmap.get(32)) for ch in text]
    adv = [hmtx[g][0] * k + tracking for g in names]
    width = sum(adv) - tracking
    cx = x - width / 2 if anchor == "middle" else x - width if anchor == "end" else x
    out = []
    for g, a in zip(names, adv):
        pen = SVGPathPen(gs, ntos=n)
        gs[g].draw(TransformPen(pen, (k, 0, 0, -k, cx, y)))
        out.append((cx, pen.getCommands()))
        cx += a
    return out, width


def text_path(text, size, x, y, fill, anchor="start", weight="Regular", tracking=0.0, extra="", mono=False):
    glyphs, _ = text_glyphs(text, GEIST_MONO if mono else GEIST[weight], size, x, y, anchor, tracking)
    d = "".join(g for _, g in glyphs)
    return f'<path d="{d}" fill="{hexc(fill)}"{extra}/>'


def svg(h, body, style=""):
    st = f"<style>{style}</style>" if style else ""
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{h}" viewBox="0 0 {W} {h}" fill="none">'
            f"{st}{body}</svg>")


REDUCED = "@media (prefers-reduced-motion:reduce){*{animation:none!important}}"


API = "https://www.alexwang.site/api/ai-activity?days=140"


def _fill_days(days):
    """Return contiguous calendar rows so quiet days still occupy chart space."""
    if not days:
        return []
    by_date = {d["date"]: d for d in days}
    start, end = date.fromisoformat(days[0]["date"]), date.fromisoformat(days[-1]["date"])
    out = []
    cur = start
    while cur <= end:
        key = cur.isoformat()
        out.append(by_date.get(key, {"date": key, "providers": {}}))
        cur += timedelta(days=1)
    return out


def public_usage():
    """Read the public fallback and preserve every provider it reports."""
    import urllib.request
    req = urllib.request.Request(API, headers={"User-Agent": "alextyhwang-profile-readme"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    days = []
    for d in data.get("days") or []:
        providers = {}
        for name, value in (d.get("providers") or {}).items():
            providers[str(name)[:24]] = {"tokens": int((value or {}).get("tokens") or 0), "cost": 0.0}
        days.append({"date": str(d["date"])[:10], "providers": providers})
    return {"v": 2, "days": _fill_days(days), "source": "public-activity"}


def feed_usage(path):
    """Extract only aggregate provider spend from t3plus-home.json.

    The feed also contains projects, automations and account limits. None of
    those fields are copied into the returned value or the rendered SVGs.
    """
    raw = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    days = []
    for key, by_provider in sorted((raw.get("spend") or {}).items()):
        providers = {}
        for name, value in (by_provider or {}).items():
            if not isinstance(value, (list, tuple)) or len(value) < 2:
                continue
            try:
                providers[str(name)[:24]] = {"cost": float(value[0] or 0), "tokens": int(value[1] or 0)}
            except (TypeError, ValueError):
                continue
        days.append({"date": str(key)[:10], "providers": providers})
    return {"v": 2, "days": _fill_days(days), "source": "t3plus-spend"}


def fmt_tokens(v):
    for unit, d in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if v >= d:
            s = f"{v / d:.1f}".rstrip("0").rstrip(".")
            return s + unit
    return str(int(v))


def fmt_cost(v):
    if v >= 1000:
        return f"${v / 1000:.1f}k"
    if v >= 100:
        return f"${v:.0f}"
    if v >= 10:
        return f"${v:.1f}"
    return f"${v:.2f}"


def provider_meta(name, theme, index):
    label, dark, light = PROVIDERS.get(name, (name.replace("_", " ").title(), *UNKNOWN_COLORS[index % len(UNKNOWN_COLORS)]))
    return label, dark if theme == "dark" else light


MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()


def area_cells(series_vals, colors, x, y, w, h, cell, flip=False, alphas=(1, 0.75)):
    """Dithered area chart (ditherCells) for daily series. Returns svg."""
    cols, rows = int(w // cell), int(h // cell)
    peak = max(max(v) for v in series_vals) or 1
    series = []
    for vals in series_vals:
        nn = len(vals)
        pts = [(i / (nn - 1), 1 - (v / peak) * 0.94) for i, v in enumerate(vals)]
        series.append({"points": pts})
    fill, edge = dither_cells(cols, rows, series)
    groups = defaultdict(list)
    for i in range(cols * rows):
        si = edge[i] if edge[i] >= 0 else fill[i]
        if si < 0:
            continue
        c, r = i % cols, i // cols
        if flip:
            r = rows - 1 - r
        groups[(si, edge[i] >= 0)].append((c, r))
    y0 = y + h - rows * cell if not flip else y
    out = []
    for (si, is_edge), cells in sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        out.append(f'<path d="{cells_path(cells, cell, ox=x, oy=y0)}" fill="{hexc(colors[si])}" '
                   f'fill-opacity="{alphas[0] if is_edge else alphas[1]}"/>')
    return f'<g shape-rendering="crispEdges">{"".join(out)}</g>', peak


def legend(th, items, x, y, size=11):
    out, cx = [], x
    for label, color in items:
        out.append(f'<rect x="{n(cx)}" y="{n(y - 8)}" width="8" height="8" fill="{hexc(color)}"/>')
        glyphs, wd = text_glyphs(label, GEIST["Regular"], size, cx + 13, y, "start")
        out.append(f'<path d="{"".join(g for _, g in glyphs)}" fill="{th["muted"]}"/>')
        cx += 13 + wd + 16
    return "".join(out)


def nice_day(d):
    dd = date.fromisoformat(d)
    return f"{MONTHS[dd.month - 1].upper()} {dd.day}"


def usage_chart(theme, usage, days=30, animate=False, metric="tokens"):
    th = THEMES[theme]
    rows = usage["days"][-days:]
    if len(rows) < 2:
        raise ValueError("usage chart needs at least two calendar days")
    names = set().union(*(r["providers"] for r in rows))
    names = [p for p in PROVIDER_ORDER if p in names] + sorted(names - set(PROVIDER_ORDER))
    series = []
    for i, name in enumerate(names):
        vals = [r["providers"].get(name, {}).get(metric, 0) for r in rows]
        # Keep all providers with activity in this window, including tokens
        # whose API-equivalent cost is currently unknown/zero.
        active = any(r["providers"].get(name, {}).get("tokens", 0) or r["providers"].get(name, {}).get("cost", 0) for r in rows)
        if active:
            label, color = provider_meta(name, theme, i)
            series.append((sum(vals), vals, color, label))
    if not series:
        series = [(0, [0] * len(rows), th["muted"], "No usage")]
    # Heaviest first, like T3's paint order.
    order = sorted(series, key=lambda s: -s[0])
    px, py, pw, ph = 44, 40, W - 46, 150
    area, peak = area_cells([s[1] for s in order], [s[2] for s in order], px, py, pw, ph, CELL)
    total = sum(s[0] for s in series)
    fmt = fmt_tokens if metric == "tokens" else fmt_cost
    heading = "AI tokens per day" if metric == "tokens" else "AI cost per day"
    suffix = " tokens" if metric == "tokens" else " API estimate"
    parts = [text_path(heading, 14, 2, 16, th["fg"], weight="Medium"),
             text_path(f"{fmt(total)}{suffix}  \u00b7  last {days} days", 12, W - 2, 16, th["muted"], "end"),
             text_path(fmt(peak).upper(), 9, 2, py + 9, th["muted"], tracking=0.6),
             text_path("0", 9, 2, py + ph, th["muted"]),
             f'<path d="M{px} {py + ph + 0.5}H{W - 2}" stroke="{th["border"]}"/>',
             f'<path d="M{px} {py + 0.5}H{W - 2}" stroke="{th["border"]}" stroke-dasharray="2 3"/>']
    for i, anchor in ((0, "start"), (len(rows) // 2, "middle"), (len(rows) - 1, "end")):
        x = px + (i / (len(rows) - 1)) * pw if anchor == "middle" else (px if anchor == "start" else W - 2)
        parts.append(text_path(nice_day(rows[i]["date"]), 9, x, py + ph + 16, th["muted"], anchor, tracking=0.6))
    # Wrap the legend as provider support grows rather than collapsing to Other.
    legend_y, line, line_w = py + ph + 40, [], 0
    for amount, _, color, label in series:
        item = (label + " " + fmt(amount), color)
        _, item_w = text_glyphs(item[0], GEIST["Regular"], 11, 0, 0)
        item_w += 29
        if line and line_w + item_w > pw:
            parts.append(legend(th, line, px, legend_y))
            legend_y += 22
            line, line_w = [], 0
        line.append(item)
        line_w += item_w
    parts.append(legend(th, line, px, legend_y))
    style = ""
    if animate:
        area = (f'<clipPath id="wipe"><rect x="{px}" y="0" width="0" height="400">'
                f'<animate attributeName="width" from="0" to="{pw}" dur="1.4s" begin="0.3s" fill="freeze" calcMode="spline" '
                f'keySplines="0.2 0 0 1" keyTimes="0;1"/></rect></clipPath><g clip-path="url(#wipe)">{area}</g>')
    result = svg(legend_y + 14, area + "".join(parts), style)
    return result.replace('fill="none">', f'fill="none" role="img"><title>{heading}, last {days} days</title>', 1)


SPIN_SECTORS = 16


SPIN_SECONDS = 9


def glow_spin(th, theme, w, h, cell, intensity, cx, cy, sx=1.0, scale_a=None):
    """The composer glow, split into angular sectors around its center. Each
    sector's opacity dips in turn, so a soft band of light circles the glow like
    an accretion disk. Cells never move (the pixel grid stays crisp); only the
    sector opacities animate, so the file barely grows."""
    cols, rows = w // cell, h // cell
    tones = glow_tones(th["accent"], theme)
    scale = scale_a if scale_a is not None else 0.6 + 0.4 * intensity
    groups = defaultdict(list)
    for y in range(rows):
        for x in range(cols):
            u, v = (x + 0.5) / cols, (y + 0.5) / rows
            m = glow_strength(u, v, cx, intensity, cy=cy, sx=sx)
            if m <= 0:
                continue
            lv = dither_level(min(m, 0.9), len(tones), thr(x, y))
            if not lv:
                continue
            # Angle on the glow's own ellipse, so sectors are even all the way round.
            a = math.atan2((v - cy) / GLOW["haloRy"], (u - cx) / (GLOW["haloRx"] * sx))
            sector = int(((a + math.pi) / (2 * math.pi)) * SPIN_SECTORS) % SPIN_SECTORS
            groups[(sector, lv)].append((x, y))
    out = []
    for sector in range(SPIN_SECTORS):
        delay = -SPIN_SECONDS * sector / SPIN_SECTORS
        paths = "".join(f'<path d="{cells_path(c, cell)}" fill="{hexc(tones[lv][0])}" fill-opacity="{n(tones[lv][1] * scale)}"/>'
                        for (sec, lv), c in sorted(groups.items()) if sec == sector)
        out.append(f'<g class="s" style="animation-delay:{delay:.3f}s">{paths}</g>')
    return f'<g class="br">{"".join(out)}</g>'


SPIN_CSS = (".s{animation:sp %ds linear infinite}@keyframes sp{0%%,100%%{opacity:1}50%%{opacity:.5}}"
            ".br{animation:br 6s ease-in-out infinite}@keyframes br{0%%,100%%{opacity:1}50%%{opacity:.82}}" % SPIN_SECONDS)


def header_b(theme):
    th = THEMES[theme]
    h = 230
    glow = glow_spin(th, theme, W, h, CELL, 0.75, cx=0.5, cy=0.66, sx=1.25, scale_a=0.85)
    card_x, card_y, card_w, card_h = (W - 580) // 2, 42, 580, 116
    text = "Hi, I\u2019m Alex Tyh Wang"
    glyphs, tw = text_glyphs(text, GEIST["Regular"], 27, card_x + 24, card_y + 46)
    step = 0.075
    chars = "".join(f'<path class="t" style="animation-delay:{0.5 + i * step:.3f}s" d="{d}" fill="{th["fg"]}"/>'
                    for i, (_, d) in enumerate(glyphs) if d)
    end_x = card_x + 24 + tw + 3
    xs = [x for x, _ in glyphs] + [end_x - 3]
    caret_vals = ";".join(n(x + 2) for x in xs)
    caret = (f'<rect x="{n(card_x + 26)}" y="{card_y + 25}" width="2" height="27" fill="{hexc(th["accent"])}">'
             f'<animate attributeName="x" values="{caret_vals}" dur="{len(xs) * step:.3f}s" begin="0.5s" fill="freeze" calcMode="discrete"/>'
             f'<animate attributeName="opacity" values="1;0" dur="1.1s" begin="0s" repeatCount="indefinite" calcMode="discrete"/></rect>')
    sub = ""
    chip = text_path("Opus 5.5  High", 12, card_x + card_w - 58, card_y + 92, th["muted"], "end")
    send = (f'<circle cx="{card_x + card_w - 32}" cy="{card_y + 88}" r="14" fill="{th["fg"]}" fill-opacity="0.12"/>'
            f'<path d="M{card_x + card_w - 32} {card_y + 94}v-12m-5 5 5-5 5 5" stroke="{th["fg"]}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>')
    card = (f'<rect x="{card_x + 0.5}" y="{card_y + 0.5}" width="{card_w}" height="{card_h}" rx="18" fill="{th["card"]}" '
            f'fill-opacity="0.72" stroke="{th["border"]}"/>')
    foot = text_path("alextyhwang", 11, card_x + 16, card_y + card_h + 22, th["muted"], mono=True)
    foot += text_path("Auto", 11, card_x + card_w - 16, card_y + card_h + 22, th["muted"], "end")
    style = (".t{animation:ty .01s step-end backwards}@keyframes ty{from{opacity:0}}" + SPIN_CSS + REDUCED)
    return svg(h, f'<g shape-rendering="crispEdges">{glow}</g>' + card + chars + caret + sub + chip + send + foot, style)


BOT_COLORS = {
    "blue": ("#a8d1ff", "#3b82f6", "#1e2f8a"),
    "gray": ("#ececf0", "#7a7a85", "#26262c"),
    "orange": ("#ffd59e", "#f97316", "#7c2d12"),
    "purple": ("#ddd0ff", "#8b5cf6", "#3b0a64"),
}


BOT_LIGHT = (0.3, 0.26)


BTN = 16


GLYPHS = {
    "linkedin": """
................
................
................
...##...........
...##...........
................
...##.##.###....
...##.#######...
...##.###..##...
...##.##...##...
...##.##...##...
...##.##...##...
...##.##...##...
................
................
................""",
    "x": """
................
................
................
...###.....##...
....###...##....
.....###.##.....
......####......
.......###......
.......####.....
......##.###....
.....##...###...
....##.....###..
................
................
................
................""",
    "email": """
................
................
................
................
..############..
..##........##..
..#.##....##.#..
..#...####...#..
..#..........#..
..#..........#..
..#..........#..
..############..
................
................
................
................""",
    "website": """
................
................
................
.....######.....
....#..##..#....
...#..#..#..#...
...#..#..#..#...
...##########...
...#..#..#..#...
...#..#..#..#...
....#..##..#....
.....######.....
................
................
................
................""",
}


def bot_index(x, y, cols, rows, boost=0.0):
    """t3+ botArt.js ditherIndex: stop 0 light, 1 mid, 2 dark, lit from the top left."""
    cx = (x + 0.5) / cols - BOT_LIGHT[0]
    cy = (y + 0.5) / rows - BOT_LIGHT[1]
    t = max(0.0, min(1.0, math.hypot(cx, cy) / 0.95 - boost))
    v = t * 2
    band = min(1, math.floor(v))
    return band + 1 if v - band > thr(x, y) else band


def bot_tile(stops, glyph):
    """A t3+ bot-style tile: three dithered stops, the mark outlined in the dark
    stop like the bots' eyes, and the mark itself dithered from white (top) into
    the light stop (bottom) so it is not flat white."""
    rows = [r for r in glyph.strip("\n").splitlines()]
    mark = {(x, y) for y, r in enumerate(rows) for x, ch in enumerate(r) if ch == "#"}
    outline = {(x + dx, y + dy) for x, y in mark for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))} - mark
    ys = [y for _, y in mark]
    top, span = min(ys), max(1, max(ys) - min(ys))
    layers = defaultdict(list)
    for y in range(BTN):
        for x in range(BTN):
            if (x, y) in mark:
                share = 0.1 + 0.45 * (y - top) / span  # light-stop share grows downward
                idx = 0 if share > thr(x + 5, y + 2) else 3
            else:
                # Darker than a bot body (boost < 0) so the light mark reads on it.
                idx = bot_index(x, y, BTN, BTN, boost=-0.32)
            layers[idx].append((x, y))
    fills = [*stops, "#ffffff"]
    s = BTN * CELL
    clip = f'<clipPath id="c"><rect x="1" y="1" width="{s - 2}" height="{s - 2}" rx="{n(0.26 * s)}"/></clipPath>'
    body = "".join(f'<path d="{cells_path(c, CELL)}" fill="{fills[i]}"/>' for i, c in sorted(layers.items()))
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{s}" height="{s}" viewBox="0 0 {s} {s}" fill="none">'
            f'<defs>{clip}</defs><g clip-path="url(#c)" shape-rendering="crispEdges">{body}</g></svg>')


def main(argv):
    if len(argv) not in (3, 5) or argv[1] not in ("usage", "static") or (len(argv) == 5 and argv[3] != "--feed"):
        print(__doc__)
        return 2
    out = pathlib.Path(argv[2])
    out.mkdir(parents=True, exist_ok=True)
    files = {}
    if argv[1] == "usage":
        usage = feed_usage(argv[4]) if len(argv) == 5 else public_usage()
        if not usage["days"]:
            raise SystemExit("ai-activity returned no days")
        for theme in THEMES:
            files[f"usage-{theme}.svg"] = usage_chart(theme, usage)
            if usage["source"] == "t3plus-spend":
                files[f"cost-{theme}.svg"] = usage_chart(theme, usage, metric="cost")
    else:
        for theme in THEMES:
            files[f"header-{theme}.svg"] = header_b(theme)
        colors = {"linkedin": "blue", "x": "gray", "email": "orange", "website": "purple"}
        for name, color in colors.items():
            files[f"{name}.svg"] = bot_tile(BOT_COLORS[color], GLYPHS[name])
    for name, content in files.items():
        (out / name).write_text(content, encoding="utf-8", newline="\n")
        print(f"{name}: {len(content.encode()) / 1024:.1f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
