from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError
from django.test import TestCase

from films.models import Credit, Film, Genre, Person


class FilmModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_genres", verbosity=0)

    def test_str(self):
        film = Film.objects.create(title="M", year=1931)
        self.assertEqual(str(film), "M (1931)")

    def test_title_year_unique(self):
        Film.objects.create(title="M", year=1931)
        with self.assertRaises(IntegrityError):
            Film.objects.create(title="M", year=1931)

    def test_same_title_different_year_allowed(self):
        Film.objects.create(title="Nosferatu", year=1922)
        Film.objects.create(title="Nosferatu", year=1979)  # no exception

    def test_rating_validators(self):
        film = Film.objects.create(title="A", year=1920, rating=11)
        with self.assertRaises(ValidationError):
            film.full_clean()

    def test_genre_limit_in_clean(self):
        film = Film.objects.create(title="A", year=1920)
        film.genres.set(Genre.objects.all()[:4])
        with self.assertRaises(ValidationError):
            film.clean()

    def test_three_genres_pass_clean(self):
        film = Film.objects.create(title="A", year=1920)
        film.genres.set(Genre.objects.all()[:3])
        film.clean()  # no exception


class CreditModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.film = Film.objects.create(title="M", year=1931)
        cls.person = Person.objects.create(name="Fritz Lang")

    def test_unique_film_person_role(self):
        Credit.objects.create(film=self.film, person=self.person, role="dir")
        with self.assertRaises(IntegrityError):
            Credit.objects.create(film=self.film, person=self.person, role="dir")

    def test_same_person_two_roles_allowed(self):
        Credit.objects.create(film=self.film, person=self.person, role="dir")
        Credit.objects.create(film=self.film, person=self.person, role="writ")
        self.assertEqual(self.film.credits.count(), 2)


class GenreSeedTests(TestCase):
    def test_seed_is_idempotent(self):
        call_command("seed_genres", verbosity=0)
        first = Genre.objects.count()
        call_command("seed_genres", verbosity=0)
        self.assertEqual(Genre.objects.count(), first)
        self.assertEqual(first, 20)

    def test_seed_keeps_order(self):
        call_command("seed_genres", verbosity=0)
        slugs = list(Genre.objects.order_by("order").values_list("slug", flat=True))
        self.assertEqual(slugs[0], "adventure")
        self.assertEqual(slugs[-1], "western")
