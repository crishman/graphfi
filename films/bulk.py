"""Batch input parsing.

Line format: `Title | year | rating | date | genres`. The first two fields
are required. Parsing never touches the database — only preview annotation
and applying do.
"""

import datetime
from dataclasses import dataclass, field

from django.db import transaction

from .genres import GENRE_SLUGS, MAX_GENRES_PER_FILM


@dataclass
class Row:
    line_no: int
    title: str
    year: int
    rating: int | None = None
    watched_at: datetime.date | None = None
    genres: list[str] = field(default_factory=list)
    status: str = ""  # filled by preview: "new" or "update"


@dataclass
class RowError:
    line_no: int
    message: str


def parse_date(raw):
    """DD.MM.YYYY or YYYY-MM-DD -> date, anything else -> None. Shared by
    batch input and the film-card rating widget."""
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def parse_text(text):
    """Returns (rows, errors). Lines starting with # and blank lines are
    skipped; every error carries its 1-based line number."""
    rows, errors = [], []
    seen = {}
    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 2:
            errors.append(RowError(line_no, "Expected at least `Title | year`."))
            continue
        if len(parts) > 5:
            errors.append(RowError(line_no, "More than 5 fields — stray `|`?"))
            continue
        parts += [""] * (5 - len(parts))
        title, year_raw, rating_raw, date_raw, genres_raw = parts

        if not title:
            errors.append(RowError(line_no, "Empty title."))
            continue
        if not (year_raw.isdigit() and 1870 <= int(year_raw) <= 2100):
            errors.append(RowError(line_no, f"Year must be 1870–2100, got '{year_raw}'."))
            continue
        year = int(year_raw)

        rating = None
        if rating_raw:
            if not (rating_raw.isdigit() and 1 <= int(rating_raw) <= 10):
                errors.append(
                    RowError(line_no, f"Rating must be a whole 1–10, got '{rating_raw}'.")
                )
                continue
            rating = int(rating_raw)

        watched_at = None
        if date_raw:
            watched_at = parse_date(date_raw)
            if watched_at is None:
                errors.append(
                    RowError(line_no, f"Date must be DD.MM.YYYY or YYYY-MM-DD, got '{date_raw}'.")
                )
                continue

        genres = []
        if genres_raw:
            genres = [g.strip().lower() for g in genres_raw.split(",") if g.strip()]
            unknown = [g for g in genres if g not in GENRE_SLUGS]
            if unknown:
                errors.append(
                    RowError(line_no, f"Unknown genre slugs: {', '.join(unknown)}.")
                )
                continue
            if len(genres) > MAX_GENRES_PER_FILM:
                errors.append(
                    RowError(line_no, f"No more than {MAX_GENRES_PER_FILM} genres.")
                )
                continue

        key = (title.lower(), year)
        if key in seen:
            errors.append(
                RowError(line_no, f"Duplicate of line {seen[key]}: {title} ({year}).")
            )
            continue
        seen[key] = line_no
        rows.append(Row(line_no, title, year, rating, watched_at, genres))
    return rows, errors


def preview_rows(rows):
    """Marks each row as 'new' or 'update' against the current database."""
    from .models import Film

    existing = set()
    if rows:
        titles = [r.title for r in rows]
        for title, year in Film.objects.filter(title__in=titles).values_list("title", "year"):
            existing.add((title.lower(), year))
    for row in rows:
        row.status = "update" if (row.title.lower(), row.year) in existing else "new"
    return rows


@transaction.atomic
def apply_rows(rows):
    """Creates or updates films by (title, year). Only fields present in a
    row are written — an empty rating in the text never erases one in the
    database."""
    from .models import Film, Genre

    genre_map = {g.slug: g for g in Genre.objects.all()}
    created = updated = 0
    for row in rows:
        film = Film.objects.filter(title__iexact=row.title, year=row.year).first()
        if film is None:
            film = Film.objects.create(title=row.title, year=row.year)
            created += 1
        else:
            updated += 1
        if row.rating is not None:
            film.rating = row.rating
        if row.watched_at is not None:
            film.watched_at = row.watched_at
        film.save()
        if row.genres:
            film.genres.set([genre_map[slug] for slug in row.genres])
    return {"created": created, "updated": updated}
