import csv
import datetime
import io
import tempfile
from pathlib import Path

from django.core.management import CommandError, call_command
from django.test import TestCase

from films.models import Film, Genre


def run(*args, **kwargs):
    out, err = io.StringIO(), io.StringIO()
    call_command(*args, stdout=out, stderr=err, **kwargs)
    return out.getvalue(), err.getvalue()


class CsvRoundtripTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_genres", verbosity=0)
        g = {x.slug: x for x in Genre.objects.all()}
        film = Film.objects.create(
            title="The Kid", year=1921, rating=9,
            watched_at=datetime.date(2026, 1, 11), tmdb_id=10098,
        )
        film.genres.set([g["comedy"], g["drama"]])
        Film.objects.create(title="Bare", year=1929)

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = str(Path(self.dir.name) / "films.csv")

    def export(self):
        run("export_csv", "--out", self.path)
        with open(self.path, newline="", encoding="utf-8") as fh:
            return list(csv.DictReader(fh))

    def write(self, rows, fieldnames):
        with open(self.path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    def test_export_contents(self):
        rows = self.export()
        self.assertEqual(len(rows), 2)
        kid = next(r for r in rows if r["title"] == "The Kid")
        self.assertEqual(kid["rating"], "9")
        self.assertEqual(kid["genres"], "comedy,drama")
        self.assertEqual(kid["watched_at"], "2026-01-11")

    def test_roundtrip_is_idempotent(self):
        self.export()
        out, _ = run("import_csv", self.path)
        self.assertIn("0 created, 2 updated", out)
        self.assertEqual(Film.objects.count(), 2)

    def test_dry_run_touches_nothing(self):
        rows = self.export()
        for row in rows:
            row["rating"] = "1"
        self.write(rows, list(rows[0]))
        out, _ = run("import_csv", self.path, "--dry-run")
        self.assertIn("Database untouched", out)
        self.assertEqual(Film.objects.get(title="The Kid").rating, 9)

    def test_import_updates_and_creates(self):
        rows = self.export()
        kid = next(r for r in rows if r["title"] == "The Kid")
        kid["rating"] = "10"
        rows.append({"title": "Nosferatu", "year": "1922", "rating": "8",
                     "genres": "horror"})
        self.write(rows, list(rows[0]))
        out, _ = run("import_csv", self.path)
        self.assertIn("1 created, 2 updated", out)
        self.assertEqual(Film.objects.get(title="The Kid").rating, 10)
        nosferatu = Film.objects.get(title="Nosferatu")
        self.assertEqual(list(nosferatu.genres.values_list("slug", flat=True)), ["horror"])

    def test_match_by_tmdb_id_allows_retitle(self):
        self.write(
            [{"tmdb_id": "10098", "title": "The Kid (retitled)", "year": "1921"}],
            ["tmdb_id", "title", "year"],
        )
        run("import_csv", self.path)
        self.assertEqual(Film.objects.filter(year=1921).count(), 1)
        self.assertEqual(Film.objects.get(tmdb_id=10098).title, "The Kid (retitled)")

    def test_present_empty_cell_clears_field(self):
        self.write([{"title": "The Kid", "year": "1921", "rating": ""}],
                   ["title", "year", "rating"])
        run("import_csv", self.path)
        self.assertIsNone(Film.objects.get(title="The Kid").rating)

    def test_bad_rows_roll_back_good_ones(self):
        self.write(
            [{"title": "Good Film", "year": "1950", "rating": "7"},
             {"title": "Bad Film", "year": "abc", "rating": "7"}],
            ["title", "year", "rating"],
        )
        with self.assertRaises(CommandError):
            run("import_csv", self.path)
        self.assertFalse(Film.objects.filter(title="Good Film").exists())

    def test_unknown_column_rejected(self):
        self.write([{"title": "A", "year": "1950", "director": "X"}],
                   ["title", "year", "director"])
        with self.assertRaises(CommandError):
            run("import_csv", self.path)

    def test_unknown_genre_rejected(self):
        self.write([{"title": "A", "year": "1950", "genres": "noirr"}],
                   ["title", "year", "genres"])
        with self.assertRaises(CommandError):
            run("import_csv", self.path)
