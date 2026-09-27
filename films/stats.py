"""Aggregates.

Pure functions over the database: they render nothing and return plain
Python structures. charts.py consumes their output without touching the
ORM, so everything a chart needs must be computed here.
"""

from django.conf import settings
from django.db.models import Avg, Count, Max, Min, Q

from .models import Credit, Film, Person, Season, SeasonCredit, Series

# Display order for role blocks and tables.
ROLE_ORDER = [
    Credit.Role.DIRECTOR,
    Credit.Role.ACTOR,
    Credit.Role.CINEMATOGRAPHER,
    Credit.Role.COMPOSER,
    Credit.Role.WRITER,
]

ROLE_LABELS = dict(Credit.Role.choices)

# Film form. The same credit means something different in a feature, a
# two-reeler and a cartoon, so the tables for these roles are sliced by it.
# Derived from genre and runtime every time — nothing is stored.
FORM_FEATURE, FORM_SHORT, FORM_ANIMATION = "feature", "short", "animation"
FORM_ORDER = [FORM_FEATURE, FORM_SHORT, FORM_ANIMATION]
FORM_LABELS = {FORM_FEATURE: "Features", FORM_SHORT: "Shorts", FORM_ANIMATION: "Animation"}
SPLIT_ROLES = {Credit.Role.DIRECTOR, Credit.Role.ACTOR, Credit.Role.CINEMATOGRAPHER}

# The feature cast alone is split into actors and actresses. Shorts,
# animation and every other role keep one table each — the owner's call.
CAST_GENDERS = [Person.Gender.MALE, Person.Gender.FEMALE]
CAST_LABELS = {Person.Gender.MALE: ("Actor", "Actors"),
               Person.Gender.FEMALE: ("Actress", "Actresses")}


def film_form(film):
    """Animation wins over length; an unknown runtime counts as a feature.
    Mirrors films_of_form — the tests check the two agree."""
    if any(g.slug == "animation" for g in film.genres.all()):
        return FORM_ANIMATION
    if film.runtime is not None and film.runtime <= settings.SHORT_FILM_MAX_MINUTES:
        return FORM_SHORT
    return FORM_FEATURE


def films_of_form(form):
    """The rule of film_form as a queryset, for slicing people tables."""
    animated = Film.objects.filter(genres__slug="animation")
    if form == FORM_ANIMATION:
        return animated
    rest = Film.objects.exclude(genres__slug="animation")
    if form == FORM_SHORT:
        return rest.filter(runtime__lte=settings.SHORT_FILM_MAX_MINUTES)
    if form == FORM_FEATURE:
        return rest.filter(
            Q(runtime__gt=settings.SHORT_FILM_MAX_MINUTES) | Q(runtime__isnull=True)
        )
    raise ValueError(f"Unknown film form {form!r}")


def overview():
    rated = Film.objects.filter(rating__isnull=False)
    agg = rated.aggregate(
        n=Count("id"), avg=Avg("rating"), first=Min("year"), last=Max("year")
    )
    span = (agg["last"] - agg["first"] + 1) if agg["n"] else 0
    return {
        "total": Film.objects.count(),
        "rated": agg["n"],
        "avg": agg["avg"],
        "first_year": agg["first"],
        "last_year": agg["last"],
        "span": span,
        "years_covered": rated.values("year").distinct().count(),
    }


def rail_years():
    """One entry per release year from the first rated year to the last,
    including years with nothing watched — the gaps are the point."""
    per_year = {
        row["year"]: row
        for row in Film.objects.filter(rating__isnull=False)
        .values("year")
        .annotate(count=Count("id"), avg=Avg("rating"))
    }
    if not per_year:
        return []
    first, last = min(per_year), max(per_year)
    return [
        {
            "year": year,
            "count": per_year[year]["count"] if year in per_year else 0,
            "avg": per_year[year]["avg"] if year in per_year else None,
        }
        for year in range(first, last + 1)
    ]


def ratings_scatter(axis="year"):
    """Points for the rating scatter.

    axis="year"    — X is the release year, plus a yearly-average line.
    axis="watched" — X is the watch date (ISO string), no average line.
    """
    qs = Film.objects.filter(rating__isnull=False)
    if axis == "watched":
        points = [
            {"x": film.watched_at.isoformat(), "rating": film.rating,
             "title": film.title, "year": film.year, "pk": film.pk}
            for film in qs.filter(watched_at__isnull=False).order_by("watched_at")
        ]
        return {"axis": axis, "points": points, "avg_line": []}
    points = [
        {"x": film.year, "rating": film.rating,
         "title": film.title, "year": film.year, "pk": film.pk}
        for film in qs.order_by("year")
    ]
    avg_line = [
        (row["year"], row["avg"])
        for row in qs.values("year").annotate(avg=Avg("rating")).order_by("year")
    ]
    return {"axis": axis, "points": points, "avg_line": avg_line}


def rating_histogram():
    counts = dict(
        Film.objects.filter(rating__isnull=False)
        .values_list("rating")
        .annotate(n=Count("id"))
    )
    return [{"rating": r, "count": counts.get(r, 0)} for r in range(1, 11)]


def genre_averages():
    rows = (
        Film.objects.filter(rating__isnull=False)
        .values("genres__slug", "genres__label")
        .exclude(genres__slug__isnull=True)
        .annotate(count=Count("id"), avg=Avg("rating"))
        .order_by("-avg")
    )
    return [
        {"slug": row["genres__slug"], "label": row["genres__label"],
         "count": row["count"], "avg": row["avg"]}
        for row in rows
    ]


def genre_decade_matrix():
    """Average rating per genre x decade. Genres sorted by total film
    count, decades cover the whole watched range without holes."""
    triples = (
        Film.objects.filter(rating__isnull=False, genres__isnull=False)
        .values_list("genres__slug", "genres__label", "year", "rating")
    )
    if not triples:
        return {"decades": [], "rows": []}

    cells = {}   # (slug, decade) -> [sum, count]
    totals = {}  # slug -> count
    labels = {}
    for slug, label, year, rating in triples:
        decade = year - year % 10
        acc = cells.setdefault((slug, decade), [0, 0])
        acc[0] += rating
        acc[1] += 1
        totals[slug] = totals.get(slug, 0) + 1
        labels[slug] = label

    first = min(decade for _, decade in cells)
    last = max(decade for _, decade in cells)
    decades = list(range(first, last + 10, 10))
    rows = []
    for slug in sorted(totals, key=lambda s: -totals[s]):
        row_cells = []
        for decade in decades:
            acc = cells.get((slug, decade))
            row_cells.append(
                {"decade": decade, "avg": acc[0] / acc[1], "count": acc[1]}
                if acc else None
            )
        rows.append({"slug": slug, "label": labels[slug],
                     "total": totals[slug], "cells": row_cells})
    return {"decades": decades, "rows": rows}


def people_for_role(role, min_films=None, form=None, gender=None):
    """Ranked people for one role, split at the ranking threshold: an
    average over one or two films is noise, so the short tail goes into a
    collapsed block instead of burying the real top. With a form, only
    credits on films of that form count; with a gender, only people of it."""
    if min_films is None:
        min_films = settings.MIN_FILMS_FOR_RANKING
    filters = {"credits__role": role, "credits__film__rating__isnull": False}
    if form is not None:
        filters["credits__film__in"] = films_of_form(form)
    if gender is not None:
        filters["gender"] = gender
    label, title = CAST_LABELS.get(gender, (ROLE_LABELS[role], f"{ROLE_LABELS[role]}s"))
    qs = (
        Person.objects.filter(**filters)
        .annotate(
            film_count=Count("credits__film", distinct=True),
            avg_rating=Avg("credits__film__rating"),
        )
        .order_by("-film_count", "-avg_rating", "name")
    )
    ranked, rest = [], []
    for person in qs:
        entry = {
            "pk": person.pk,
            "name": person.name,
            "photo_url": person.photo_url,
            "count": person.film_count,
            "avg": person.avg_rating,
        }
        (ranked if person.film_count >= min_films else rest).append(entry)
    return {"role": role, "label": label, "title": title, "ranked": ranked,
            "rest": rest, "min_films": min_films,
            "form": form, "form_label": FORM_LABELS.get(form),
            "forms": [(f, FORM_LABELS[f]) for f in FORM_ORDER] if form else []}


def splits_by_gender(role, form):
    return role == Credit.Role.ACTOR and form == FORM_FEATURE


def people_tables(role, form=None):
    """The tables for one role and form: the feature cast as actors and
    actresses, everything else as the single table it always was."""
    if splits_by_gender(role, form):
        return [people_for_role(role, form=form, gender=g) for g in CAST_GENDERS]
    return [people_for_role(role, form=form)]


def cast_outside_split():
    """Rated-feature actors in neither split table — no gender on record,
    or non-binary — listed so that nobody silently drops out."""
    return list(
        Person.objects.filter(
            Q(gender__isnull=True) | Q(gender=Person.Gender.NON_BINARY),
            credits__role=Credit.Role.ACTOR,
            credits__film__rating__isnull=False,
            credits__film__in=films_of_form(FORM_FEATURE),
        ).distinct().order_by("name")
    )


def _summary(credits):
    ratings = [c.film.rating for c in credits if c.film.rating is not None]
    return {"count": len(credits),
            "avg": sum(ratings) / len(ratings) if ratings else None}


def person_roles(person):
    """The person's films grouped by role, with a per-role average. For the
    sliced roles, a per-form breakdown too — but only when the person
    actually spans more than one form."""
    blocks = []
    for role in ROLE_ORDER:
        credits = list(
            person.credits.filter(role=role)
            .select_related("film")
            .prefetch_related("film__genres")
            .order_by("film__year", "film__title")
        )
        if not credits:
            continue
        by_form = {}
        if role in SPLIT_ROLES:
            for credit in credits:
                by_form.setdefault(film_form(credit.film), []).append(credit)
        label = ROLE_LABELS[role]
        if role == Credit.Role.ACTOR and person.gender in CAST_LABELS:
            label = CAST_LABELS[person.gender][0]
        blocks.append({
            "role": role,
            "label": label,
            "credits": credits,
            **_summary(credits),
            "forms": [
                {"form": f, "label": FORM_LABELS[f], **_summary(by_form[f])}
                for f in FORM_ORDER if f in by_form
            ] if len(by_form) > 1 else [],
        })
    return blocks


def film_credits(film):
    """The film's credits grouped by role, in display order. In a cartoon
    the cast is voices, and the label says so."""
    labels = dict(ROLE_LABELS)
    if film_form(film) == FORM_ANIMATION:
        labels[Credit.Role.ACTOR] = "Voice actor"
    by_role = {}
    for credit in film.credits.select_related("person").order_by("billing", "id"):
        by_role.setdefault(credit.role, []).append(credit)
    return [
        {"role": role, "label": labels[role], "credits": by_role[role]}
        for role in ROLE_ORDER
        if role in by_role
    ]


def same_year_films(film):
    return list(
        Film.objects.filter(year=film.year).exclude(pk=film.pk).order_by("title")
    )


# -- TV ------------------------------------------------------------------
# Everything below reads Series / Season / SeasonCredit only; nothing
# above reads them, so film numbers cannot move when series are added.

SEASON_ROLE_ORDER = [SeasonCredit.Role.CREATOR, SeasonCredit.Role.ACTOR, SeasonCredit.Role.DIRECTOR]


def series_rating(series):
    """A series' rating: the average of its rated seasons, never stored."""
    return series.seasons.filter(rating__isnull=False).aggregate(avg=Avg("rating"))["avg"]


def season_span(numbers):
    """[1, 2, 3] -> "S1–3", [1, 3] -> "S1, S3"."""
    numbers = sorted(set(numbers))
    runs, start = [], None
    for i, n in enumerate(numbers):
        if start is None:
            start = n
        if i + 1 == len(numbers) or numbers[i + 1] != n + 1:
            runs.append(f"S{start}" if start == n else f"S{start}–{n}")
            start = None
    return ", ".join(runs)


def series_credits(series):
    """The series' people by role, each person once with the seasons they
    are in: creators, the cast in billing order, directors by episodes
    directed. In a cartoon the cast is voices."""
    animated = series.genres.filter(slug="animation").exists()
    labels = {
        SeasonCredit.Role.CREATOR: "Creator",
        SeasonCredit.Role.ACTOR: "Voice actor" if animated else "Actor",
        SeasonCredit.Role.DIRECTOR: "Director",
    }
    entries = {}
    for credit in (SeasonCredit.objects.filter(season__series=series)
                   .select_related("person", "season").order_by("season__number", "billing", "id")):
        entry = entries.setdefault((credit.role, credit.person_id), {
            "person": credit.person, "character": credit.character,
            "numbers": [], "episodes": 0, "billing": credit.billing,
        })
        entry["numbers"].append(credit.season.number)
        entry["episodes"] += credit.episodes or 0
        if credit.billing is not None and (entry["billing"] is None or credit.billing < entry["billing"]):
            entry["billing"] = credit.billing
    sort_keys = {
        SeasonCredit.Role.CREATOR: lambda e: e["person"].name,
        SeasonCredit.Role.ACTOR: lambda e: (e["billing"] is None, e["billing"] or 0, e["person"].name),
        SeasonCredit.Role.DIRECTOR: lambda e: (-e["episodes"], e["person"].name),
    }
    blocks = []
    for role in SEASON_ROLE_ORDER:
        people = sorted((e for (r, _), e in entries.items() if r == role), key=sort_keys[role])
        for e in people:
            e["seasons"] = season_span(e["numbers"])
        if people:
            blocks.append({"role": role, "label": labels[role], "people": people})
    return blocks
