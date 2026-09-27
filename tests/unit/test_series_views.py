import datetime

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from films import stats
from films.models import Genre, Person, Season, SeasonCredit, Series


def make_twin_peaks():
    series = Series.objects.create(title="Twin Peaks", first_year=1990, last_year=2017, tmdb_id=1920)
    series.genres.set(Genre.objects.filter(slug__in=["drama", "mystery"]))
    s1 = Season.objects.create(series=series, number=1, name="Season 1", year=1990, episode_count=8, rating=9)
    s2 = Season.objects.create(series=series, number=2, name="Season 2", year=1990, episode_count=22, rating=7)
    s3 = Season.objects.create(series=series, number=3, name="The Return", year=2017, episode_count=18)
    kyle = Person.objects.create(name="Kyle MacLachlan", gender=Person.Gender.MALE)
    lynch = Person.objects.create(name="David Lynch", gender=Person.Gender.MALE)
    lee = Person.objects.create(name="Sheryl Lee", gender=Person.Gender.FEMALE)
    for s in (s1, s2, s3):
        SeasonCredit.objects.create(season=s, person=kyle, role="act", character="Dale Cooper", billing=0)
        SeasonCredit.objects.create(season=s, person=lynch, role="crea")
    SeasonCredit.objects.create(season=s1, person=lee, role="act", character="Laura Palmer", billing=3)
    SeasonCredit.objects.create(season=s3, person=lee, role="act", character="Laura Palmer", billing=5)
    SeasonCredit.objects.create(season=s1, person=lynch, role="dir", episodes=2)
    SeasonCredit.objects.create(season=s3, person=lynch, role="dir", episodes=18)
    return series


class SeasonSpanTests(SimpleTestCase):
    def test_runs_and_gaps(self):
        self.assertEqual(stats.season_span([1, 2, 3]), "S1–3")
        self.assertEqual(stats.season_span([3, 1]), "S1, S3")
        self.assertEqual(stats.season_span([1, 2, 4, 5, 7]), "S1–2, S4–5, S7")
        self.assertEqual(stats.season_span([2]), "S2")


class SeriesStatsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_genres", verbosity=0)
        cls.series = make_twin_peaks()

    def test_series_rating_is_average_of_rated_seasons(self):
        self.assertAlmostEqual(stats.series_rating(self.series), 8)
        Season.objects.filter(series=self.series).update(rating=None)
        self.assertIsNone(stats.series_rating(self.series))

    def test_series_credits_grouped_each_person_once(self):
        blocks = {b["role"]: b for b in stats.series_credits(self.series)}
        self.assertEqual([b["role"] for b in stats.series_credits(self.series)], ["crea", "act", "dir"])
        cast = [(e["person"].name, e["seasons"]) for e in blocks["act"]["people"]]
        self.assertEqual(cast, [("Kyle MacLachlan", "S1–3"), ("Sheryl Lee", "S1, S3")])
        director = blocks["dir"]["people"][0]
        self.assertEqual((director["person"].name, director["episodes"], director["seasons"]),
                         ("David Lynch", 20, "S1, S3"))
        self.assertEqual(blocks["act"]["label"], "Actor")

    def test_cartoon_cast_labelled_as_voices(self):
        self.series.genres.add(Genre.objects.get(slug="animation"))
        blocks = {b["role"]: b for b in stats.series_credits(self.series)}
        self.assertEqual(blocks["act"]["label"], "Voice actor")


class SeriesViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_genres", verbosity=0)
        cls.series = make_twin_peaks()
        cls.lucy = Series.objects.create(title="I Love Lucy", first_year=1951, last_year=1957)
        Season.objects.create(series=cls.lucy, number=1, year=1951, rating=8)

    def test_nav_links_series(self):
        self.assertContains(self.client.get("/"), 'href="/series/"')

    def test_list_shows_season_counts_and_average(self):
        response = self.client.get("/series/")
        self.assertContains(response, "Twin Peaks")
        self.assertContains(response, "1990–2017")
        self.assertContains(response, "2 / 3")
        self.assertContains(response, "8.0")

    def test_year_filter_uses_season_air_year_and_keeps_the_full_average(self):
        response = self.client.get("/series/?year=2017")
        self.assertContains(response, "Twin Peaks")          # its third season aired in 2017
        self.assertNotContains(response, "I Love Lucy")
        self.assertContains(response, "2 / 3")               # not narrowed to the 2017 season
        response = self.client.get("/series/?decade=1950")
        self.assertContains(response, "I Love Lucy")
        self.assertNotContains(response, "Twin Peaks")

    def test_list_sorting_and_search(self):
        body = self.client.get("/series/?sort=year").content.decode()
        self.assertLess(body.index("I Love Lucy"), body.index("Twin Peaks"))
        response = self.client.get("/series/?q=lucy")
        self.assertContains(response, "I Love Lucy")
        self.assertNotContains(response, "Twin Peaks")

    def test_empty_list_renders(self):
        Series.objects.all().delete()
        self.assertContains(self.client.get("/series/"), "No series yet")

    def test_detail_shows_seasons_rating_and_people(self):
        response = self.client.get(f"/series/{self.series.pk}/")
        self.assertContains(response, "average of the rated seasons")
        self.assertContains(response, 'id="season-3"')
        self.assertContains(response, "The Return")          # a real season name is shown
        self.assertNotContains(response, '<span class="hint">Season 1</span>', html=False)
        self.assertContains(response, "Creator")
        self.assertContains(response, "Dale Cooper")
        self.assertContains(response, "20 ep.")
        self.assertContains(response, "https://www.themoviedb.org/tv/1920")

    def test_detail_404(self):
        self.assertEqual(self.client.get("/series/99999/").status_code, 404)


class RateSeasonTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.series = Series.objects.create(title="Das Boot", first_year=1985)
        cls.season = Season.objects.create(series=cls.series, number=1, year=1985)

    def url(self):
        return f"/season/{self.season.pk}/rate/"

    def test_rating_saved_with_default_date_and_redirect_to_the_row(self):
        response = self.client.post(self.url(), {"rating": "9"})
        self.assertRedirects(response, f"/series/{self.series.pk}/#season-1", fetch_redirect_response=False)
        self.season.refresh_from_db()
        self.assertEqual(self.season.rating, 9)
        self.assertIsNotNone(self.season.watched_at)

    def test_explicit_date_keep_and_clear(self):
        self.client.post(self.url(), {"rating": "7", "watched_at": "20.08.2026"})
        self.season.refresh_from_db()
        self.assertEqual((self.season.rating, self.season.watched_at), (7, datetime.date(2026, 8, 20)))
        self.client.post(self.url(), {"rating": "clear"})
        self.season.refresh_from_db()
        self.assertEqual((self.season.rating, self.season.watched_at), (None, datetime.date(2026, 8, 20)))

    def test_garbage_ignored(self):
        for raw in ("0", "11", "9.5", "ten"):
            self.client.post(self.url(), {"rating": raw})
        self.season.refresh_from_db()
        self.assertIsNone(self.season.rating)

    def test_get_does_not_write(self):
        self.client.get(self.url())
        self.season.refresh_from_db()
        self.assertIsNone(self.season.rating)
