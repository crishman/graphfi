from django.urls import path

from . import views

urlpatterns = [
    path("", views.profile, name="profile"),
    path("films/", views.film_list, name="film_list"),
    path("film/<int:pk>/", views.film_detail, name="film_detail"),
    path("people/", views.people, name="people"),
    path("person/<int:pk>/", views.person_detail, name="person_detail"),
    path("add/", views.bulk_add, name="bulk_add"),
]
