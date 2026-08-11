import re
import xml.etree.ElementTree as ET

from django.test import SimpleTestCase

from films import charts


def well_formed(svg):
    ET.fromstring(svg)
    return True


class RatingColorTests(SimpleTestCase):
    def test_anchor_values(self):
        self.assertEqual(charts.rating_color(1), "#3D4E5A")
        self.assertEqual(charts.rating_color(5.5), "#8C8A78")
        self.assertEqual(charts.rating_color(10), "#F0B44E")

    def test_none_is_empty_frame(self):
        self.assertEqual(charts.rating_color(None), charts.EMPTY_FRAME)

    def test_out_of_range_clamps(self):
        self.assertEqual(charts.rating_color(0), charts.rating_color(1))
        self.assertEqual(charts.rating_color(-5), charts.rating_color(1))
        self.assertEqual(charts.rating_color(11), charts.rating_color(10))

    def test_interpolation_monotonic_warmth(self):
        # Red channel must grow with the rating: the lamp warms up.
        reds = [int(charts.rating_color(v)[1:3], 16) for v in range(1, 11)]
        self.assertEqual(reds, sorted(reds))


class RailSvgTests(SimpleTestCase):
    def years(self):
        return [
            {"year": 1920, "count": 2, "avg": 7.5},
            {"year": 1921, "count": 0, "avg": None},
            {"year": 1922, "count": 1, "avg": 10.0},
        ]

    def test_empty_returns_placeholder(self):
        svg = charts.rail_svg([])
        self.assertIn("chart-empty", svg)
        self.assertTrue(well_formed(svg))

    def test_one_frame_and_link_per_year(self):
        svg = charts.rail_svg(self.years())
        self.assertTrue(well_formed(svg))
        self.assertEqual(svg.count("/films/?year="), 3)
        self.assertIn("/films/?year=1921", svg)  # empty years are frames too

    def test_empty_year_uses_empty_frame_color(self):
        svg = charts.rail_svg(self.years())
        self.assertIn(charts.EMPTY_FRAME, svg)
        self.assertIn("1921 — nothing yet", svg)

    def test_decade_labels_only(self):
        svg = charts.rail_svg(self.years())
        self.assertIn(">1920<", svg)
        self.assertNotIn(">1921<", svg)
        self.assertNotIn(">1922<", svg)


class ScatterSvgTests(SimpleTestCase):
    def data(self):
        return {
            "axis": "year",
            "points": [
                {"x": 1920, "rating": 8, "title": "A & B <C>", "year": 1920, "pk": 1},
                {"x": 1920, "rating": 8, "title": "Twin", "year": 1920, "pk": 2},
                {"x": 1931, "rating": 10, "title": "M", "year": 1931, "pk": 3},
            ],
            "avg_line": [(1920, 8.0), (1931, 10.0)],
        }

    def test_empty_returns_placeholder(self):
        svg = charts.scatter_svg({"axis": "year", "points": [], "avg_line": []})
        self.assertIn("chart-empty", svg)

    def test_points_links_and_escaping(self):
        svg = charts.scatter_svg(self.data())
        self.assertTrue(well_formed(svg))
        self.assertEqual(svg.count("<circle"), 3)
        self.assertIn("/film/1/", svg)
        self.assertIn("A &amp; B &lt;C&gt; (1920) — 8", svg)

    def test_average_line_drawn_for_year_axis(self):
        self.assertIn("<polyline", charts.scatter_svg(self.data()))

    def test_no_average_line_for_watched_axis(self):
        data = {
            "axis": "watched",
            "points": [
                {"x": "2026-01-04", "rating": 8, "title": "A", "year": 1920, "pk": 1},
                {"x": "2026-03-01", "rating": 9, "title": "B", "year": 1925, "pk": 2},
            ],
            "avg_line": [],
        }
        svg = charts.scatter_svg(data)
        self.assertTrue(well_formed(svg))
        self.assertNotIn("<polyline", svg)

    def test_coinciding_points_spread_horizontally(self):
        svg = charts.scatter_svg(self.data())
        xs = [float(m) for m in re.findall(r"circle cx='([\d.]+)'", svg)]
        # The two 1920/8 twins must not share an x coordinate.
        self.assertNotEqual(xs[0], xs[1])


class GenreBarsSvgTests(SimpleTestCase):
    def test_empty_returns_placeholder(self):
        self.assertIn("chart-empty", charts.genre_bars_svg([]))

    def test_bars_lengths_follow_average(self):
        rows = [
            {"slug": "crime", "label": "Crime", "count": 1, "avg": 10.0},
            {"slug": "drama", "label": "Drama", "count": 4, "avg": 5.0},
        ]
        svg = charts.genre_bars_svg(rows)
        self.assertTrue(well_formed(svg))
        widths = [float(m) for m in re.findall(r"rect [^>]*width='([\d.]+)'", svg)]
        self.assertAlmostEqual(widths[0] / widths[1], 2.0, places=1)
        self.assertIn("/films/?genre=crime", svg)


class HeatmapSvgTests(SimpleTestCase):
    def matrix(self):
        return {
            "decades": [1920, 1930],
            "rows": [
                {"slug": "comedy", "label": "Comedy", "total": 3, "cells": [
                    {"decade": 1920, "avg": 9.0, "count": 2},
                    {"decade": 1930, "avg": 8.0, "count": 1},
                ]},
                {"slug": "noir", "label": "Noir", "total": 1, "cells": [
                    None,
                    {"decade": 1930, "avg": 7.0, "count": 1},
                ]},
            ],
        }

    def test_empty_returns_placeholder(self):
        self.assertIn("chart-empty", charts.heatmap_svg({"decades": [], "rows": []}))

    def test_cells_headers_and_gaps(self):
        svg = charts.heatmap_svg(self.matrix())
        self.assertTrue(well_formed(svg))
        self.assertIn(">1920s<", svg)
        self.assertIn(">1930s<", svg)
        self.assertIn("Comedy, 1920s — avg 9.0 over 2 films", svg)
        # 3 filled cells linked, 1 empty unlinked
        self.assertEqual(svg.count("<a href="), 3)
        self.assertIn(charts.EMPTY_FRAME, svg)


class HistogramSvgTests(SimpleTestCase):
    def bins(self, counts):
        return [{"rating": i, "count": c} for i, c in enumerate(counts, start=1)]

    def test_empty_returns_placeholder(self):
        self.assertIn("chart-empty", charts.histogram_svg(self.bins([0] * 10)))

    def test_all_ten_bars_present(self):
        svg = charts.histogram_svg(self.bins([0, 0, 0, 1, 0, 2, 3, 5, 4, 1]))
        self.assertTrue(well_formed(svg))
        for rating in range(1, 11):
            self.assertIn(f">{rating}<", svg)
        self.assertIn("8 — 5 films", svg)
        self.assertIn("4 — 1 film<", svg)
