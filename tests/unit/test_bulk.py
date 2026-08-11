import datetime

from django.core.management import call_command
from django.test import TestCase

from films import bulk
from films.models import Film


class ParseTextTests(TestCase):
    """Parsing is DB-free, but TestCase keeps everything uniform."""

    def test_full_row(self):
        rows, errors = bulk.parse_text("Metropolis | 1927 | 9 | 20.03.2026 | scifi, drama")
        self.assertEqual(errors, [])
        row = rows[0]
        self.assertEqual(
            (row.title, row.year, row.rating, row.watched_at, row.genres),
            ("Metropolis", 1927, 9, datetime.date(2026, 3, 20), ["scifi", "drama"]),
        )

    def test_minimal_row(self):
        rows, errors = bulk.parse_text("Nosferatu | 1922")
        self.assertEqual(errors, [])
        self.assertEqual((rows[0].title, rows[0].year), ("Nosferatu", 1922))
        self.assertIsNone(rows[0].rating)

    def test_iso_date_accepted(self):
        rows, _ = bulk.parse_text("A | 1950 | 5 | 1999-12-31")
        self.assertEqual(rows[0].watched_at, datetime.date(1999, 12, 31))

    def test_comments_and_blank_lines_skipped(self):
        rows, errors = bulk.parse_text("# comment\n\nThe Kid | 1921\n   \n# more")
        self.assertEqual(len(rows), 1)
        self.assertEqual(errors, [])

    def test_error_line_numbers_are_exact(self):
        text = "Good | 1920\nbad line\nAlso Good | 1921\nWorse | 20x0"
        rows, errors = bulk.parse_text(text)
        self.assertEqual(len(rows), 2)
        self.assertEqual([e.line_no for e in errors], [2, 4])

    def test_bad_year(self):
        _, errors = bulk.parse_text("A | 1492")
        self.assertIn("1870", errors[0].message)

    def test_rating_out_of_range(self):
        for raw in ("0", "11", "5.5", "ten"):
            _, errors = bulk.parse_text(f"A | 1920 | {raw}")
            self.assertEqual(len(errors), 1, raw)

    def test_impossible_date(self):
        _, errors = bulk.parse_text("A | 1920 | 5 | 31.02.2026")
        self.assertEqual(len(errors), 1)

    def test_unknown_genre(self):
        _, errors = bulk.parse_text("A | 1920 | 5 | | fantasyy")
        self.assertIn("fantasyy", errors[0].message)

    def test_too_many_genres(self):
        _, errors = bulk.parse_text("A | 1920 | 5 | | drama, war, noir, spy")
        self.assertIn("3", errors[0].message)

    def test_duplicate_rows_rejected(self):
        _, errors = bulk.parse_text("The Kid | 1921\nthe kid | 1921")
        self.assertEqual(len(errors), 1)
        self.assertIn("line 1", errors[0].message)

    def test_too_many_fields(self):
        _, errors = bulk.parse_text("A | 1920 | 5 | 2026-01-01 | drama | extra")
        self.assertIn("|", errors[0].message)


class PreviewAndApplyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_genres", verbosity=0)
        Film.objects.create(title="The Kid", year=1921, rating=9,
                            watched_at=datetime.date(2026, 1, 11))

    def test_preview_marks_new_and_update(self):
        rows, _ = bulk.parse_text("The Kid | 1921 | 10\nNosferatu | 1922")
        rows = bulk.preview_rows(rows)
        self.assertEqual([r.status for r in rows], ["update", "new"])

    def test_apply_creates_and_updates_without_duplicates(self):
        rows, _ = bulk.parse_text("The Kid | 1921 | 10\nNosferatu | 1922 | 8 | | horror")
        result = bulk.apply_rows(rows)
        self.assertEqual(result, {"created": 1, "updated": 1})
        self.assertEqual(Film.objects.count(), 2)
        kid = Film.objects.get(title="The Kid")
        self.assertEqual(kid.rating, 10)
        nosferatu = Film.objects.get(title="Nosferatu")
        self.assertEqual(list(nosferatu.genres.values_list("slug", flat=True)), ["horror"])

    def test_apply_does_not_erase_missing_fields(self):
        rows, _ = bulk.parse_text("The Kid | 1921")
        bulk.apply_rows(rows)
        kid = Film.objects.get(title="The Kid")
        self.assertEqual(kid.rating, 9)
        self.assertEqual(kid.watched_at, datetime.date(2026, 1, 11))

    def test_apply_matches_title_case_insensitively(self):
        rows, _ = bulk.parse_text("the kid | 1921 | 7")
        result = bulk.apply_rows(rows)
        self.assertEqual(result, {"created": 0, "updated": 1})
        self.assertEqual(Film.objects.count(), 1)
