"""SVG generation.

Takes stats.py output, returns SVG strings. Never queries the database
and never imports Django — the whole module is testable with plain data.

Interactivity without JS: dots and cells are wrapped in <a href>, hints go
through <title>. User-supplied text is escaped with html.escape before it
lands inside markup.
"""

import datetime
import html

# Projection-booth palette, shared with style.css.
TEXT = "#dcd7cc"
MUTED = "#7e8b97"
RULE = "#27333e"
AMBER = "#e8a33c"
EMPTY_FRAME = "#1B242D"
GROUND = "#0f151b"

MONO = "font-family='IBM Plex Mono, monospace'"

# The rating scale is the lamp of a projector: cold and dim at 1, warm and
# bright at 10.
_ANCHORS = [
    (1.0, (0x3D, 0x4E, 0x5A)),
    (5.5, (0x8C, 0x8A, 0x78)),
    (10.0, (0xF0, 0xB4, 0x4E)),
]


def rating_color(value):
    if value is None:
        return EMPTY_FRAME
    v = min(max(float(value), 1.0), 10.0)
    for (v0, c0), (v1, c1) in zip(_ANCHORS, _ANCHORS[1:]):
        if v <= v1:
            t = (v - v0) / (v1 - v0)
            r, g, b = (round(a + (b_ - a) * t) for a, b_ in zip(c0, c1))
            return f"#{r:02X}{g:02X}{b:02X}"
    return f"#{_ANCHORS[-1][1][0]:02X}{_ANCHORS[-1][1][1]:02X}{_ANCHORS[-1][1][2]:02X}"


def _svg(width, height, body, css_class="chart"):
    return (
        f"<svg class='{css_class}' viewBox='0 0 {width} {height}' width='{width}' "
        f"height='{height}' xmlns='http://www.w3.org/2000/svg' role='img'>{body}</svg>"
    )


def _placeholder(message, width=640, height=90):
    text = html.escape(message)
    body = (
        f"<rect x='0.5' y='0.5' width='{width - 1}' height='{height - 1}' rx='6' "
        f"fill='{EMPTY_FRAME}' stroke='{RULE}'/>"
        f"<text x='{width / 2}' y='{height / 2}' fill='{MUTED}' font-size='14' "
        f"text-anchor='middle' dominant-baseline='central'>{text}</text>"
    )
    return _svg(width, height, body, css_class="chart chart-empty")


def rail_svg(years, url_pattern="/films/?year={year}"):
    """The film strip: one frame per release year, empty years included.
    This is the signature picture of progress — everything else on the
    profile is secondary."""
    if not years:
        return _placeholder("No rated films yet — the strip will appear here.")

    frame_w, frame_h, gap = 16, 26, 5
    pad = 8
    perf_h = 5          # sprocket hole row height
    label_h = 18
    top = pad + perf_h + 4
    width = pad * 2 + len(years) * (frame_w + gap) - gap
    height = top + frame_h + 4 + perf_h + label_h + pad

    parts = []
    for i, entry in enumerate(years):
        x = pad + i * (frame_w + gap)
        year, avg, count = entry["year"], entry["avg"], entry["count"]
        # Sprocket holes above and below the frame.
        for py in (pad, top + frame_h + 4):
            parts.append(
                f"<rect x='{x + frame_w / 2 - 3}' y='{py}' width='6' height='{perf_h}' "
                f"rx='1.5' fill='{RULE}'/>"
            )
        if avg is None:
            tip = f"{year} — nothing yet"
        else:
            films = "film" if count == 1 else "films"
            tip = f"{year} — {count} {films}, avg {avg:.1f}"
        href = html.escape(url_pattern.format(year=year))
        parts.append(
            f"<a href='{href}'>"
            f"<rect x='{x}' y='{top}' width='{frame_w}' height='{frame_h}' rx='2' "
            f"fill='{rating_color(avg)}' stroke='{RULE}'>"
            f"<title>{html.escape(tip)}</title></rect></a>"
        )
        if year % 10 == 0:
            parts.append(
                f"<text x='{x + frame_w / 2}' y='{height - pad}' fill='{MUTED}' "
                f"font-size='11' text-anchor='middle' {MONO}>{year}</text>"
            )
    return _svg(width, height, "".join(parts), css_class="chart chart-rail")


def _spread_overlaps(points, key):
    """Horizontal offsets for points sharing the same (x, rating), so they
    do not merge into one dot."""
    groups = {}
    for p in points:
        groups.setdefault(key(p), []).append(p)
    offsets = {}
    for group in groups.values():
        for i, p in enumerate(group):
            offsets[id(p)] = (i - (len(group) - 1) / 2) * 5
    return offsets


def scatter_svg(data, url_pattern="/film/{pk}/"):
    """Ratings scatter: X is the release year (with a yearly-average line)
    or the watch date, Y is the 1–10 rating."""
    points = data["points"]
    if not points:
        return _placeholder("No ratings yet — the scatter will appear here.")

    by_date = data["axis"] == "watched"
    width, height = 960, 300
    ml, mr, mt, mb = 40, 16, 12, 34
    plot_w, plot_h = width - ml - mr, height - mt - mb

    if by_date:
        xs = [datetime.date.fromisoformat(p["x"]).toordinal() for p in points]
    else:
        xs = [p["x"] for p in points]
    xmin, xmax = min(xs), max(xs)
    if xmin == xmax:
        xmin, xmax = xmin - 1, xmax + 1

    def px(x):
        return ml + (x - xmin) / (xmax - xmin) * plot_w

    def py(rating):
        return mt + (10 - rating) / 9 * plot_h

    parts = []
    for r in range(1, 11):
        y = py(r)
        parts.append(
            f"<line x1='{ml}' y1='{y}' x2='{width - mr}' y2='{y}' "
            f"stroke='{RULE}' stroke-width='{1.5 if r == 1 else 0.5}'/>"
            f"<text x='{ml - 8}' y='{y}' fill='{MUTED}' font-size='11' "
            f"text-anchor='end' dominant-baseline='central' {MONO}>{r}</text>"
        )

    if by_date:
        first = datetime.date.fromordinal(xmin).year
        last = datetime.date.fromordinal(xmax).year
        tick_years = range(first, last + 1)
        step = max(1, (last - first + 1) // 12)
        tick_positions = [
            (datetime.date(y, 1, 1).toordinal(), str(y))
            for y in tick_years if (y - first) % step == 0
        ]
    else:
        first = xmin - xmin % 10
        tick_positions = [(y, str(y)) for y in range(first, xmax + 1, 10) if y >= xmin]
    for tx, label in tick_positions:
        if not xmin <= tx <= xmax:
            continue
        x = px(tx)
        parts.append(
            f"<line x1='{x}' y1='{mt}' x2='{x}' y2='{height - mb}' "
            f"stroke='{RULE}' stroke-width='0.5'/>"
            f"<text x='{x}' y='{height - mb + 16}' fill='{MUTED}' font-size='11' "
            f"text-anchor='middle' {MONO}>{label}</text>"
        )

    if data["avg_line"]:
        line = " ".join(f"{px(x):.1f},{py(avg):.1f}" for x, avg in data["avg_line"])
        parts.append(
            f"<polyline points='{line}' fill='none' stroke='{MUTED}' "
            f"stroke-width='1.5' stroke-opacity='0.8'/>"
        )

    offsets = _spread_overlaps(points, key=lambda p: (p["x"], p["rating"]))
    for p, x in zip(points, xs):
        cx = px(x) + offsets[id(p)]
        tip = f"{p['title']} ({p['year']}) — {p['rating']}"
        href = html.escape(url_pattern.format(pk=p["pk"]))
        parts.append(
            f"<a href='{href}'>"
            f"<circle cx='{cx:.1f}' cy='{py(p['rating']):.1f}' r='4.5' "
            f"fill='{rating_color(p['rating'])}' stroke='{GROUND}' stroke-width='1'>"
            f"<title>{html.escape(tip)}</title></circle></a>"
        )
    return _svg(width, height, "".join(parts))


def genre_bars_svg(rows, url_pattern="/films/?genre={slug}"):
    """Horizontal bars: length and colour are the genre average, the film
    count sits to the right."""
    if not rows:
        return _placeholder("No genres to chart yet.")

    row_h, label_w, count_w = 28, 150, 70
    width = 640
    bar_max = width - label_w - count_w
    height = len(rows) * row_h + 8
    parts = []
    for i, row in enumerate(rows):
        y = 4 + i * row_h
        bar_w = max(row["avg"] / 10 * bar_max, 2)
        tip = f"{row['label']} — avg {row['avg']:.1f} over {row['count']}"
        href = html.escape(url_pattern.format(slug=row["slug"]))
        parts.append(
            f"<a href='{href}'>"
            f"<text x='{label_w - 10}' y='{y + row_h / 2}' fill='{TEXT}' font-size='13' "
            f"text-anchor='end' dominant-baseline='central'>{html.escape(row['label'])}</text>"
            f"<rect x='{label_w}' y='{y + 5}' width='{bar_w:.1f}' height='{row_h - 10}' "
            f"rx='2' fill='{rating_color(row['avg'])}'>"
            f"<title>{html.escape(tip)}</title></rect>"
            f"<text x='{label_w + bar_w + 8:.1f}' y='{y + row_h / 2}' fill='{TEXT}' "
            f"font-size='12' dominant-baseline='central' {MONO}>{row['avg']:.1f}</text>"
            f"<text x='{width - 4}' y='{y + row_h / 2}' fill='{MUTED}' font-size='12' "
            f"text-anchor='end' dominant-baseline='central' {MONO}>{row['count']}</text>"
            f"</a>"
        )
    return _svg(width, height, "".join(parts))


def heatmap_svg(matrix, url_pattern="/films/?genre={slug}&decade={decade}"):
    """Genre x decade matrix: each cell is the average rating, shown as
    colour and number. Genres are sorted by total film count."""
    if not matrix["rows"]:
        return _placeholder("The genre x decade matrix needs rated films.")

    cell_w, cell_h, gap = 46, 27, 3
    label_w, header_h = 150, 24
    width = label_w + len(matrix["decades"]) * (cell_w + gap)
    height = header_h + len(matrix["rows"]) * (cell_h + gap) + 4

    parts = []
    for j, decade in enumerate(matrix["decades"]):
        x = label_w + j * (cell_w + gap) + cell_w / 2
        parts.append(
            f"<text x='{x}' y='{header_h - 8}' fill='{MUTED}' font-size='11' "
            f"text-anchor='middle' {MONO}>{decade}s</text>"
        )
    for i, row in enumerate(matrix["rows"]):
        y = header_h + i * (cell_h + gap)
        parts.append(
            f"<text x='{label_w - 10}' y='{y + cell_h / 2}' fill='{TEXT}' font-size='13' "
            f"text-anchor='end' dominant-baseline='central'>{html.escape(row['label'])}</text>"
        )
        for j, cell in enumerate(row["cells"]):
            x = label_w + j * (cell_w + gap)
            if cell is None:
                parts.append(
                    f"<rect x='{x}' y='{y}' width='{cell_w}' height='{cell_h}' rx='2' "
                    f"fill='{EMPTY_FRAME}'/>"
                )
                continue
            films = "film" if cell["count"] == 1 else "films"
            tip = (
                f"{row['label']}, {cell['decade']}s — avg {cell['avg']:.1f} "
                f"over {cell['count']} {films}"
            )
            # Warm cells get dark digits, cold cells light ones.
            ink = GROUND if cell["avg"] >= 6.5 else TEXT
            href = html.escape(
                url_pattern.format(slug=row["slug"], decade=cell["decade"])
            )
            parts.append(
                f"<a href='{href}'>"
                f"<rect x='{x}' y='{y}' width='{cell_w}' height='{cell_h}' rx='2' "
                f"fill='{rating_color(cell['avg'])}'>"
                f"<title>{html.escape(tip)}</title></rect>"
                f"<text x='{x + cell_w / 2}' y='{y + cell_h / 2}' fill='{ink}' "
                f"font-size='11' text-anchor='middle' dominant-baseline='central' "
                f"{MONO}>{cell['avg']:.1f}</text></a>"
            )
    return _svg(width, height, "".join(parts))


def histogram_svg(bins):
    """Distribution of 1–10 ratings."""
    if not any(b["count"] for b in bins):
        return _placeholder("No ratings yet — the histogram will appear here.")

    bar_w, gap, plot_h = 44, 12, 150
    ml, mt, mb = 8, 20, 24
    width = ml * 2 + len(bins) * (bar_w + gap) - gap
    height = mt + plot_h + mb
    peak = max(b["count"] for b in bins)

    parts = [
        f"<line x1='{ml}' y1='{mt + plot_h}' x2='{width - ml}' y2='{mt + plot_h}' "
        f"stroke='{RULE}'/>"
    ]
    for i, b in enumerate(bins):
        x = ml + i * (bar_w + gap)
        bar_h = b["count"] / peak * plot_h if b["count"] else 0
        y = mt + plot_h - bar_h
        films = "film" if b["count"] == 1 else "films"
        parts.append(
            f"<rect x='{x}' y='{y:.1f}' width='{bar_w}' height='{max(bar_h, 1):.1f}' "
            f"rx='2' fill='{rating_color(b['rating']) if b['count'] else EMPTY_FRAME}'>"
            f"<title>{b['rating']} — {b['count']} {films}</title></rect>"
            f"<text x='{x + bar_w / 2}' y='{mt + plot_h + 16}' fill='{MUTED}' "
            f"font-size='12' text-anchor='middle' {MONO}>{b['rating']}</text>"
        )
        if b["count"]:
            parts.append(
                f"<text x='{x + bar_w / 2}' y='{y - 6:.1f}' fill='{TEXT}' "
                f"font-size='11' text-anchor='middle' {MONO}>{b['count']}</text>"
            )
    return _svg(width, height, "".join(parts))
