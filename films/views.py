"""Views are glue: stats + charts + template. No logic lives here."""

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Avg, Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.safestring import mark_safe

from . import bulk, charts, stats
from .models import Credit, Film, Genre, Person, Season, Series

SORTS = {
    "-year": ["-year", "title"],
    "year": ["year", "title"],
    "-rating": ["-rating", "-year"],
    "rating": ["rating", "-year"],
    "-watched": ["-watched_at", "-year"],
    "watched": ["watched_at", "-year"],
    "title": ["title"],
}


SEASON_UNIT = ("season", "seasons")


def profile(request):
    axis = "watched" if request.GET.get("axis") == "watched" else "year"
    if request.GET.get("kind") == "series":
        return _series_profile(request, axis)
    # The profile carries the survey's spine — features — for the sliced
    # roles; shorts and animation are one link away.
    people = [
        table
        for role in stats.ROLE_ORDER
        for table in stats.people_tables(
            role, form=stats.FORM_FEATURE if role in stats.SPLIT_ROLES else None
        )
    ]
    context = {
        "overview": stats.overview(),
        "rail": mark_safe(charts.rail_svg(stats.rail_years())),
        "scatter": mark_safe(charts.scatter_svg(stats.ratings_scatter(axis))),
        "axis": axis,
        "histogram": mark_safe(charts.histogram_svg(stats.rating_histogram())),
        "genre_bars": mark_safe(charts.genre_bars_svg(stats.genre_averages())),
        "heatmap": mark_safe(charts.heatmap_svg(stats.genre_decade_matrix())),
        "people_tables": people,
    }
    return render(request, "films/profile.html", context)


def _series_profile(request, axis):
    """The profile's other half: the same pictures over rated seasons, and
    the TV tables for actors and directors. The film view never reads a
    season, and this one never reads a film."""
    context = {
        "kind": "series",
        "overview": stats.series_overview(),
        "rail": mark_safe(charts.rail_svg(stats.series_rail_years(),
                                          url_pattern="/series/?year={year}", unit=SEASON_UNIT)),
        "scatter": mark_safe(charts.scatter_svg(stats.series_scatter(axis),
                                                url_pattern="/series/{pk}/")),
        "axis": axis,
        "histogram": mark_safe(charts.histogram_svg(stats.series_rating_histogram(), unit=SEASON_UNIT)),
        "genre_bars": mark_safe(charts.genre_bars_svg(stats.series_genre_averages(),
                                                      url_pattern="/series/?genre={slug}")),
        "heatmap": mark_safe(charts.heatmap_svg(stats.series_genre_decade_matrix(),
                                                url_pattern="/series/?genre={slug}&decade={decade}",
                                                unit=SEASON_UNIT)),
        "people_tables": [stats.series_people_for_role(role)
                          for role in stats.ROLE_ORDER if role in stats.TV_ROLES],
    }
    return render(request, "films/profile.html", context)


def film_list(request):
    films = Film.objects.all().prefetch_related("genres")

    q = request.GET.get("q", "").strip()
    if q:
        films = films.filter(Q(title__icontains=q) | Q(original_title__icontains=q))
    year = request.GET.get("year", "").strip()
    if year.isdigit():
        films = films.filter(year=int(year))
    decade = request.GET.get("decade", "").strip()
    if decade.isdigit():
        films = films.filter(year__gte=int(decade), year__lt=int(decade) + 10)
    genre = request.GET.get("genre", "").strip()
    if genre:
        films = films.filter(genres__slug=genre)
    if request.GET.get("unrated"):
        films = films.filter(rating__isnull=True)
    sort = request.GET.get("sort", "-year")
    films = films.order_by(*SORTS.get(sort, SORTS["-year"]))

    page = Paginator(films, 60).get_page(request.GET.get("page"))
    params = request.GET.copy()
    params.pop("page", None)
    context = {
        "page": page,
        "genres": Genre.objects.all(),
        "q": q,
        "year": year,
        "decade": decade,
        "genre": genre,
        "unrated": bool(request.GET.get("unrated")),
        "sort": sort,
        "sorts": SORTS,
        "querystring": params.urlencode(),
    }
    return render(request, "films/film_list.html", context)


def _rating_buttons():
    # The 1-10 buttons carry the lamp scale; warm cells need dark digits.
    return [
        (value, charts.rating_color(value),
         charts.GROUND if value >= 7 else charts.TEXT)
        for value in range(1, 11)
    ]


def film_detail(request, pk):
    film = get_object_or_404(Film.objects.prefetch_related("genres"), pk=pk)
    context = {
        "film": film,
        "credit_blocks": stats.film_credits(film),
        "same_year": stats.same_year_films(film),
        "rating_color": charts.rating_color(film.rating),
        "rating_buttons": _rating_buttons(),
        "today": timezone.localdate(),
    }
    return render(request, "films/film_detail.html", context)


def _apply_rating(request, item):
    """The card widget's POST, for a film or a season alike: a rating
    1-10, "keep" or "clear", and an optional watch date."""
    raw = request.POST.get("rating", "")
    if raw == "clear":
        item.rating = None
    elif raw.isdigit() and 1 <= int(raw) <= 10:
        item.rating = int(raw)
    elif raw != "keep":
        return
    date_raw = request.POST.get("watched_at", "").strip()
    if date_raw:
        parsed = bulk.parse_date(date_raw)
        if parsed is None:
            messages.error(
                request,
                f"Could not read the date '{date_raw}' — "
                "use YYYY-MM-DD or DD.MM.YYYY.",
            )
        else:
            item.watched_at = parsed
    elif item.rating and item.watched_at is None:
        item.watched_at = timezone.localdate()
    item.save()
    rating = item.rating if item.rating is not None else "—"
    watched = item.watched_at.isoformat() if item.watched_at else "—"
    messages.success(request, f"{item}: rating {rating}, watched {watched}.")


def rate_film(request, pk):
    """Inline rating from the film card. Open like the batch page: the
    site has no accounts, and /add/ already writes the same two fields."""
    film = get_object_or_404(Film, pk=pk)
    if request.method == "POST":
        _apply_rating(request, film)
    return redirect(f"/film/{pk}/")


SERIES_SORTS = {
    "-year": ["-first_year", "title"],
    "year": ["first_year", "title"],
    "-rating": ["-avg", "-first_year"],
    "title": ["title"],
}


def series_list(request):
    series = Series.objects.all().prefetch_related("genres")
    q = request.GET.get("q", "").strip()
    if q:
        series = series.filter(Q(title__icontains=q) | Q(original_title__icontains=q))
    genre = request.GET.get("genre", "").strip()
    if genre:
        series = series.filter(genres__slug=genre)
    # Year and decade select by a season's air year, through a subquery so
    # the season averages below still cover every season.
    year = request.GET.get("year", "").strip()
    if year.isdigit():
        series = series.filter(pk__in=Season.objects.filter(year=int(year)).values("series"))
    decade = request.GET.get("decade", "").strip()
    if decade.isdigit():
        series = series.filter(pk__in=Season.objects.filter(
            year__gte=int(decade), year__lt=int(decade) + 10).values("series"))
    series = series.annotate(
        season_count=Count("seasons", distinct=True),
        rated_count=Count("seasons", filter=Q(seasons__rating__isnull=False), distinct=True),
        avg=Avg("seasons__rating"),
    )
    sort = request.GET.get("sort", "-year")
    series = series.order_by(*SERIES_SORTS.get(sort, SERIES_SORTS["-year"]))
    context = {
        "series_list": series,
        "genres": Genre.objects.all(),
        "q": q, "genre": genre, "year": year, "decade": decade, "sort": sort,
    }
    return render(request, "films/series_list.html", context)


def series_detail(request, pk):
    series = get_object_or_404(Series.objects.prefetch_related("genres"), pk=pk)
    rating = stats.series_rating(series)
    context = {
        "series": series,
        "rating": rating,
        "rating_color": charts.rating_color(rating),
        # TMDB names most seasons "Season N"; only a real name is shown.
        "seasons": [
            (season, charts.rating_color(season.rating),
             "" if season.name == f"Season {season.number}" else season.name)
            for season in series.seasons.all()
        ],
        "credit_blocks": stats.series_credits(series),
        "rating_buttons": _rating_buttons(),
        "today": timezone.localdate(),
    }
    return render(request, "films/series_detail.html", context)


def rate_season(request, pk):
    season = get_object_or_404(Season.objects.select_related("series"), pk=pk)
    if request.method == "POST":
        _apply_rating(request, season)
    return redirect(f"/series/{season.series_id}/#season-{season.number}")


def people(request):
    role = request.GET.get("role", Credit.Role.ACTOR)
    if role not in Credit.Role.values:
        raise Http404("Unknown role")
    form = None
    if role in stats.SPLIT_ROLES:
        form = request.GET.get("form", stats.FORM_FEATURE)
        if form not in dict(stats.people_tabs(role)):
            raise Http404("Unknown film form")
    tables = stats.people_tables(role, form=form)
    context = {
        "tables": tables,
        "forms": tables[0]["forms"],
        "form": form,
        "outside_split": stats.cast_outside_split() if stats.splits_by_gender(role, form) else [],
        "roles": [(r, stats.ROLE_LABELS[r]) for r in stats.ROLE_ORDER],
        "role": role,
    }
    return render(request, "films/people.html", context)


def person_detail(request, pk):
    person = get_object_or_404(Person, pk=pk)
    context = {
        "person": person,
        "role_blocks": stats.person_roles(person),
        "series_blocks": stats.person_series_roles(person),
    }
    return render(request, "films/person_detail.html", context)


def bulk_add(request):
    text = ""
    rows = errors = None
    if request.method == "POST":
        text = request.POST.get("text", "")
        rows, errors = bulk.parse_text(text)
        rows = bulk.preview_rows(rows)
        if request.POST.get("action") == "save" and not errors and rows:
            result = bulk.apply_rows(rows)
            messages.success(
                request,
                f"Saved: {result['created']} new, {result['updated']} updated.",
            )
            return redirect("/films/?sort=-watched")
    context = {"text": text, "rows": rows, "errors": errors}
    return render(request, "films/bulk_add.html", context)
