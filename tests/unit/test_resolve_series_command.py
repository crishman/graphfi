import io
from unittest import mock

import requests
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from films import resolver
from films.models import Credit, Film, Person, Season, SeasonCredit, Series
from tests.unit.test_tv_resolver import season_credits_payload, tv_payload


def series_data():
    return resolver.series_from_payload(tv_payload())


def season_credits(tmdb_id, number, episode_count, api_key):
    return resolver.season_credits_from_payload(season_credits_payload(), episode_count)


@override_settings(TMDB_API_KEY="fake-key")
class ResolveSeriesCommandTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_genres", verbosity=0)

    def run_command(self, *args, fetch_series=None, fetch_season=season_credits):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(resolver, "fetch_series", fetch_series or mock.Mock(return_value=series_data())), \
             mock.patch.object(resolver, "fetch_season_credits", fetch_season), \
             mock.patch.object(resolver, "search_tv",
                               return_value=[resolver.Candidate(1920, "Twin Peaks", "Twin Peaks", 1990)]):
            call_command("resolve_series", *args, stdout=out, stderr=err)
        return out.getvalue(), err.getvalue()

    def test_creates_series_seasons_and_credits(self):
        self.run_command("--tmdb", "1920")
        series = Series.objects.get()
        self.assertEqual((series.title, series.first_year, series.last_year, series.tmdb_id),
                         ("Twin Peaks", 1990, 2017, 1920))
        self.assertEqual(sorted(series.genres.values_list("slug", flat=True)), ["drama", "mystery", "scifi"])
        self.assertEqual(list(series.seasons.values_list("number", "year")),
                         [(1, 1990), (2, 1990), (3, 2017)])   # no specials
        s1 = series.seasons.get(number=1)
        roles = sorted(s1.credits.values_list("person__name", "role"))
        self.assertEqual(roles, [("David Lynch", "crea"), ("David Lynch", "dir"),
                                 ("Kyle MacLachlan", "act"), ("Mark Frost", "crea"),
                                 ("Sheryl Lee", "act"), ("Tina Rathborne", "dir")])
        self.assertEqual(Person.objects.get(name="Sheryl Lee").gender, Person.Gender.FEMALE)

    def test_search_path_with_auto(self):
        self.run_command("Twin Peaks", "--year", "1990", "--auto")
        self.assertTrue(Series.objects.filter(tmdb_id=1920).exists())

    def test_rerun_creates_no_duplicates_and_keeps_owner_edits(self):
        self.run_command("--tmdb", "1920")
        season = Season.objects.get(number=3)
        season.rating, season.note = 9, "the best of it"
        season.save()
        counts = (Series.objects.count(), Season.objects.count(), SeasonCredit.objects.count(),
                  Person.objects.count())
        self.run_command("--refresh")
        season.refresh_from_db()
        self.assertEqual((season.rating, season.note), (9, "the best of it"))
        self.assertEqual((Series.objects.count(), Season.objects.count(), SeasonCredit.objects.count(),
                          Person.objects.count()), counts)

    def test_person_from_films_gets_tv_credits_on_the_same_row(self):
        film = Film.objects.create(title="Eraserhead", year=1977, rating=8)
        lynch = Person.objects.create(name="David Lynch", tmdb_id=6)
        Credit.objects.create(film=film, person=lynch, role="dir")
        self.run_command("--tmdb", "1920")
        self.assertEqual(Person.objects.filter(name="David Lynch").count(), 1)
        self.assertEqual(lynch.season_credits.filter(role="dir").count(), 3)
        self.assertEqual(lynch.credits.count(), 1)   # the film credit untouched

    def test_manual_series_is_linked_not_duplicated(self):
        manual = Series.objects.create(title="Twin Peaks", first_year=1990, note="mine")
        self.run_command("--tmdb", "1920")
        manual.refresh_from_db()
        self.assertEqual((manual.tmdb_id, manual.note), (1920, "mine"))
        self.assertEqual(Series.objects.count(), 1)

    def test_failure_on_a_season_saves_nothing_and_hides_the_url(self):
        response = requests.Response()
        response.status_code = 401
        http_error = requests.HTTPError("401 for url: https://x/?api_key=SECRET", response=response)
        def failing(tmdb_id, number, episode_count, api_key):
            if number == 3:
                raise resolver.ResolverError(f"TMDB request failed: {http_error}") from http_error
            return season_credits(tmdb_id, number, episode_count, api_key)
        out, err = self.run_command("--tmdb", "1920", fetch_season=failing)
        self.assertEqual((Series.objects.count(), Season.objects.count(), SeasonCredit.objects.count()), (0, 0, 0))
        self.assertIn("HTTP 401", err)
        self.assertNotIn("SECRET", err + out)
        self.assertIn("failed 1", out)

    def test_needs_a_target(self):
        with self.assertRaises(CommandError):
            self.run_command()
