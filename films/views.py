"""Views are glue: stats + charts + template. No logic lives here."""

from django.shortcuts import render
from django.utils.safestring import mark_safe

from . import charts, stats


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
