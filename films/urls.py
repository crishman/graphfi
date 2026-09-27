from django.urls import path

from . import views

urlpatterns = [
    path("", views.profile, name="profile"),
    path("films/", views.film_list, name="film_list"),
    path("film/<int:pk>/", views.film_detail, name="film_detail"),
    path("film/<int:pk>/rate/", views.rate_film, name="rate_film"),
    path("series/", views.series_list, name="series_list"),
    path("series/<int:pk>/", views.series_detail, name="series_detail"),
    path("season/<int:pk>/rate/", views.rate_season, name="rate_season"),
    path("people/", views.people, name="people"),
    path("person/<int:pk>/", views.person_detail, name="person_detail"),
    path("add/", views.bulk_add, name="bulk_add"),
]
