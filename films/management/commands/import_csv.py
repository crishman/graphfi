import csv
import datetime

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from films.genres import GENRE_SLUGS, MAX_GENRES_PER_FILM
from films.models import Film, Genre

# Present columns are authoritative (an empty cell clears the field);
# absent columns are left untouched. Credits do not travel through CSV.
KNOWN_COLUMNS = {
    "id", "title", "original_title", "year", "rating", "watched_at",
    "genres", "country", "runtime", "tmdb_id", "imdb_id", "wikidata_id",
    "poster_url", "note",
}


class _DryRun(Exception):
    pass


class Command(BaseCommand):
    help = "Import films from CSV. Matching order: id, then tmdb_id, then title + year."

    def add_arguments(self, parser):
        parser.add_argument("path", help="CSV file to import.")
        parser.add_argument("--dry-run", action="store_true",
                            help="Run everything in a transaction and roll it back.")

    def handle(self, *args, **options):
        try:
            with open(options["path"], newline="", encoding="utf-8") as fh:
                reader = csv.DictReader(fh)
                if reader.fieldnames is None:
                    raise CommandError("Empty file.")
                unknown = set(reader.fieldnames) - KNOWN_COLUMNS
                if unknown:
                    raise CommandError(f"Unknown columns: {', '.join(sorted(unknown))}.")
                if not {"title", "year"} <= set(reader.fieldnames):
                    raise CommandError("Columns 'title' and 'year' are required.")
                rows = list(reader)
        except OSError as exc:
            raise CommandError(f"Cannot read {options['path']}: {exc}") from exc

        try:
            with transaction.atomic():
                created, updated, errors = self.apply(rows)
                if errors:
                    for line_no, message in errors:
                        self.stderr.write(self.style.ERROR(f"line {line_no}: {message}"))
                    raise CommandError(f"{len(errors)} bad rows — nothing imported.")
                if options["dry_run"]:
                    raise _DryRun
        except _DryRun:
            self.stdout.write(self.style.SUCCESS(
                f"Dry run: {created} would be created, {updated} updated. Database untouched."
            ))
            return
        self.stdout.write(self.style.SUCCESS(f"Imported: {created} created, {updated} updated."))

    def apply(self, rows):
        genre_map = {g.slug: g for g in Genre.objects.all()}
        created = updated = 0
        errors = []
        # Header is line 1, data starts at 2.
        for line_no, row in enumerate(rows, start=2):
            try:
                film, was_created = self.apply_row(row, genre_map)
            except ValueError as exc:
                errors.append((line_no, str(exc)))
                continue
            if was_created:
                created += 1
            else:
                updated += 1
        return created, updated, errors

    def apply_row(self, row, genre_map):
        title = (row.get("title") or "").strip()
        year_raw = (row.get("year") or "").strip()
        if not title:
            raise ValueError("Empty title.")
        if not (year_raw.isdigit() and 1870 <= int(year_raw) <= 2100):
            raise ValueError(f"Year must be 1870–2100, got '{year_raw}'.")
        year = int(year_raw)

        film = self.match(row, title, year)
        was_created = film is None
        if film is None:
            film = Film(title=title, year=year)
        else:
            film.title = title
            film.year = year

        for attr in ("original_title", "country", "imdb_id", "wikidata_id", "poster_url", "note"):
            if attr in row and row[attr] is not None:
                setattr(film, attr, row[attr].strip())

        if "rating" in row and row["rating"] is not None:
            raw = row["rating"].strip()
            if raw and not (raw.isdigit() and 1 <= int(raw) <= 10):
                raise ValueError(f"Rating must be a whole 1–10, got '{raw}'.")
            film.rating = int(raw) if raw else None

        if "watched_at" in row and row["watched_at"] is not None:
            raw = row["watched_at"].strip()
            if raw:
                try:
                    film.watched_at = datetime.date.fromisoformat(raw)
                except ValueError as exc:
                    raise ValueError(f"watched_at must be YYYY-MM-DD, got '{raw}'.") from exc
            else:
                film.watched_at = None

        if "runtime" in row and row["runtime"] is not None:
            raw = row["runtime"].strip()
            if raw and not raw.isdigit():
                raise ValueError(f"Runtime must be a number, got '{raw}'.")
            film.runtime = int(raw) if raw else None

        if "tmdb_id" in row and row["tmdb_id"] is not None:
            raw = row["tmdb_id"].strip()
            if raw and not raw.isdigit():
                raise ValueError(f"tmdb_id must be a number, got '{raw}'.")
            tmdb_id = int(raw) if raw else None
            if tmdb_id and Film.objects.filter(tmdb_id=tmdb_id).exclude(pk=film.pk).exists():
                raise ValueError(f"tmdb_id {tmdb_id} already belongs to another film.")
            film.tmdb_id = tmdb_id

        clash = Film.objects.filter(title=film.title, year=film.year).exclude(pk=film.pk).first()
        if clash:
            raise ValueError(f"'{title}' ({year}) collides with existing film id={clash.pk}.")
        film.save()

        if "genres" in row and row["genres"] is not None:
            slugs = [s.strip().lower() for s in row["genres"].split(",") if s.strip()]
            unknown = [s for s in slugs if s not in GENRE_SLUGS]
            if unknown:
                raise ValueError(f"Unknown genre slugs: {', '.join(unknown)}.")
            if len(slugs) > MAX_GENRES_PER_FILM:
                raise ValueError(f"No more than {MAX_GENRES_PER_FILM} genres.")
            film.genres.set([genre_map[s] for s in slugs])
        return film, was_created

    def match(self, row, title, year):
        raw_id = (row.get("id") or "").strip()
        if raw_id.isdigit():
            film = Film.objects.filter(pk=int(raw_id)).first()
            if film:
                return film
        raw_tmdb = (row.get("tmdb_id") or "").strip()
        if raw_tmdb.isdigit():
            film = Film.objects.filter(tmdb_id=int(raw_tmdb)).first()
            if film:
                return film
        return Film.objects.filter(title__iexact=title, year=year).first()
