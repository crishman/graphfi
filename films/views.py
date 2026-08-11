"""Views are glue: stats + charts + template. No logic lives here."""

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.safestring import mark_safe

from . import bulk, charts, stats
from .models import Credit, Film, Genre, Person

SORTS = {
    "-year": ["-year", "title"],
    "year": ["year", "title"],
    "-rating": ["-rating", "-year"],
    "rating": ["rating", "-year"],
    "-watched": ["-watched_at", "-year"],
    "watched": ["watched_at", "-year"],
    "title": ["title"],
}


def profile(request):
    axis = "watched" if request.GET.get("axis") == "watched" else "year"
    people = [stats.people_for_role(role) for role in stats.ROLE_ORDER]
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


def film_detail(request, pk):
    film = get_object_or_404(Film.objects.prefetch_related("genres"), pk=pk)
    context = {
        "film": film,
        "credit_blocks": stats.film_credits(film),
        "same_year": stats.same_year_films(film),
        "rating_color": charts.rating_color(film.rating),
        # The 1-10 buttons carry the lamp scale; warm cells need dark digits.
        "rating_buttons": [
            (value, charts.rating_color(value),
             charts.GROUND if value >= 7 else charts.TEXT)
            for value in range(1, 11)
        ],
        "today": timezone.localdate(),
    }
    return render(request, "films/film_detail.html", context)


@staff_member_required
def rate_film(request, pk):
    """Inline rating from the film card. Reuses the admin session — the
    site itself still has no accounts."""
    film = get_object_or_404(Film, pk=pk)
    if request.method == "POST":
        raw = request.POST.get("rating", "")
        if raw == "clear":
            film.rating = None
        elif raw.isdigit() and 1 <= int(raw) <= 10:
            film.rating = int(raw)
        elif raw != "keep":
            return redirect(f"/film/{pk}/")
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
                film.watched_at = parsed
        elif film.rating and film.watched_at is None:
            film.watched_at = timezone.localdate()
        film.save()
        rating = film.rating if film.rating is not None else "—"
        watched = film.watched_at.isoformat() if film.watched_at else "—"
        messages.success(request, f"{film}: rating {rating}, watched {watched}.")
    return redirect(f"/film/{pk}/")


def people(request):
    role = request.GET.get("role", Credit.Role.ACTOR)
    if role not in Credit.Role.values:
        raise Http404("Unknown role")
    context = {
        "table": stats.people_for_role(role),
        "roles": [(r, stats.ROLE_LABELS[r]) for r in stats.ROLE_ORDER],
        "role": role,
    }
    return render(request, "films/people.html", context)


def person_detail(request, pk):
    person = get_object_or_404(Person, pk=pk)
    context = {
        "person": person,
        "role_blocks": stats.person_roles(person),
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
