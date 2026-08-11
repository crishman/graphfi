"""Views are glue: stats + charts + template. No logic lives here."""

from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, render
from django.utils.safestring import mark_safe

from . import charts, stats
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
    }
    return render(request, "films/film_detail.html", context)


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
