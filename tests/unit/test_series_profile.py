import datetime

from django.core.management import call_command
from django.test import TestCase

from films import stats
from films.models import Film, Genre, Person, Season, SeasonCredit, Series


class SeriesProfileTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_genres", verbosity=0)
        g = {x.slug: x for x in Genre.objects.all()}
        cls.peaks = Series.objects.create(title="Twin Peaks", first_year=1990)
        cls.peaks.genres.set([g["drama"], g["mystery"]])
        Season.objects.create(series=cls.peaks, number=1, year=1990, rating=9,
                              watched_at=datetime.date(2026, 9, 1))
        Season.objects.create(series=cls.peaks, number=2, year=1990, rating=7)
        Season.objects.create(series=cls.peaks, number=3, year=2017, rating=10)
        cls.lucy = Series.objects.create(title="I Love Lucy", first_year=1951)
        cls.lucy.genres.set([g["comedy"]])
        Season.objects.create(series=cls.lucy, number=1, year=1951, rating=8)
        Season.objects.create(series=cls.lucy, number=2, year=1952)          # unrated
        cls.film = Film.objects.create(title="The Kid", year=1921, rating=9)
        ball = Person.objects.create(name="Lucille Ball", gender=Person.Gender.FEMALE)
        SeasonCredit.objects.create(season=cls.lucy.seasons.get(number=1), person=ball, role="act")

    def test_overview_counts_seasons(self):
        data = stats.series_overview()
        self.assertEqual((data["series"], data["total"], data["rated"]), (2, 5, 4))
        self.assertAlmostEqual(data["avg"], 8.5)
        self.assertEqual((data["first_year"], data["last_year"], data["span"], data["years_covered"]),
                         (1951, 2017, 67, 3))

    def test_rail_places_seasons_on_air_years_with_gaps(self):
        rail = {y["year"]: y for y in stats.series_rail_years()}
        self.assertEqual(rail[1990]["count"], 2)
        self.assertEqual(rail[2017]["count"], 1)
        self.assertIsNone(rail[2000]["avg"])                  # the gap is kept
        self.assertEqual(min(rail), 1951)

    def test_scatter_points_are_seasons_that_open_their_series(self):
        data = stats.series_scatter("year")
        titles = [(p["title"], p["x"], p["pk"]) for p in data["points"]]
        self.assertIn(("Twin Peaks S3", 2017, self.peaks.pk), titles)
        self.assertEqual(len(titles), 4)
        watched = stats.series_scatter("watched")
        self.assertEqual([p["title"] for p in watched["points"]], ["Twin Peaks S1"])

    def test_histogram_genres_and_matrix(self):
        bins = {b["rating"]: b["count"] for b in stats.series_rating_histogram()}
        self.assertEqual((bins[10], bins[9], bins[8], bins[7], bins[1]), (1, 1, 1, 1, 0))
        genres = {r["slug"]: r for r in stats.series_genre_averages()}
        self.assertEqual(genres["drama"]["count"], 3)
        self.assertAlmostEqual(genres["comedy"]["avg"], 8)
        matrix = stats.series_genre_decade_matrix()
        self.assertEqual(matrix["decades"][0], 1950)
        self.assertEqual(matrix["decades"][-1], 2010)

    def test_series_profile_page(self):
        response = self.client.get("/?kind=series")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<svg", count=5)
        self.assertContains(response, "<strong>Series</strong>")
        self.assertContains(response, "1 season, avg 10.0")            # rail tooltip for 2017
        self.assertContains(response, "/series/?year=2017")
        self.assertContains(response, f"/series/{self.peaks.pk}/")
        self.assertContains(response, "/people/?role=act&amp;form=tv")
        self.assertContains(response, "Lucille Ball")
        self.assertNotContains(response, "The Kid")
        self.assertContains(response, "axis=watched&amp;kind=series")

    def test_film_profile_ignores_series(self):
        response = self.client.get("/")
        self.assertContains(response, 'href="?kind=series"')
        self.assertContains(response, "1 film, avg 9.0")               # The Kid's year
        self.assertNotContains(response, "season")
        self.assertNotContains(response, "Twin Peaks")
        self.assertEqual(stats.overview()["total"], 1)

    def test_empty_database_series_profile(self):
        Season.objects.all().delete()
        Series.objects.all().delete()
        response = self.client.get("/?kind=series")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No rated seasons yet")
        self.assertContains(response, "The genre x decade matrix needs rated seasons.")
