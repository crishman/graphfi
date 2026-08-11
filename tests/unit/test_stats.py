import datetime

from django.core.management import call_command
from django.test import TestCase

from films import stats
from films.models import Credit, Film, Genre, Person


class StatsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_genres", verbosity=0)
        g = {x.slug: x for x in Genre.objects.all()}

        def film(title, year, rating=None, watched=None, genres=()):
            obj = Film.objects.create(
                title=title, year=year, rating=rating,
                watched_at=datetime.date.fromisoformat(watched) if watched else None,
            )
            obj.genres.set([g[s] for s in genres])
            return obj

        cls.caligari = film("Caligari", 1920, 8, "2026-01-04", ["horror", "fantasy"])
        cls.zorro = film("Zorro", 1920, 7, "2026-01-05", ["swashbuckler"])
        cls.kid = film("The Kid", 1921, 9, "2026-01-11", ["comedy", "drama"])
        cls.sherlock = film("Sherlock Jr.", 1924, 10, "2026-02-14", ["comedy"])
        cls.m = film("M", 1931, 10, "2026-04-02", ["crime", "thriller"])
        cls.unrated = film("Way Down East", 1920)

        cls.chaplin = Person.objects.create(name="Charlie Chaplin")
        cls.keaton = Person.objects.create(name="Buster Keaton")
        Credit.objects.create(film=cls.kid, person=cls.chaplin, role="dir")
        Credit.objects.create(film=cls.kid, person=cls.chaplin, role="act", character="Tramp")
        Credit.objects.create(film=cls.sherlock, person=cls.keaton, role="dir")
        Credit.objects.create(film=cls.sherlock, person=cls.chaplin, role="act")

    def test_overview(self):
        data = stats.overview()
        self.assertEqual(data["total"], 6)
        self.assertEqual(data["rated"], 5)
        self.assertAlmostEqual(data["avg"], 8.8)
        self.assertEqual((data["first_year"], data["last_year"]), (1920, 1931))
        self.assertEqual(data["span"], 12)
        self.assertEqual(data["years_covered"], 4)

    def test_overview_empty_database(self):
        Film.objects.all().delete()
        data = stats.overview()
        self.assertEqual(data["total"], 0)
        self.assertIsNone(data["avg"])
        self.assertEqual(data["span"], 0)

    def test_rail_years_covers_gaps(self):
        rail = stats.rail_years()
        self.assertEqual(len(rail), 12)  # 1920..1931 inclusive
        self.assertEqual(rail[0], {"year": 1920, "count": 2, "avg": 7.5})
        gap = rail[2]  # 1922: nothing watched
        self.assertEqual((gap["year"], gap["count"], gap["avg"]), (1922, 0, None))

    def test_rail_years_ignores_unrated(self):
        # The unrated 1920 film must not count toward the year average.
        self.assertEqual(stats.rail_years()[0]["count"], 2)

    def test_rail_years_empty(self):
        Film.objects.all().delete()
        self.assertEqual(stats.rail_years(), [])

    def test_scatter_by_year(self):
        data = stats.ratings_scatter()
        self.assertEqual(len(data["points"]), 5)
        self.assertEqual(data["avg_line"][0], (1920, 7.5))
        point = data["points"][0]
        self.assertEqual(set(point), {"x", "rating", "title", "year", "pk"})

    def test_scatter_by_watch_date(self):
        data = stats.ratings_scatter("watched")
        self.assertEqual(data["avg_line"], [])
        self.assertEqual(data["points"][0]["x"], "2026-01-04")

    def test_rating_histogram_has_all_bins(self):
        bins = stats.rating_histogram()
        self.assertEqual(len(bins), 10)
        counts = {b["rating"]: b["count"] for b in bins}
        self.assertEqual(counts[10], 2)
        self.assertEqual(counts[1], 0)

    def test_genre_averages_sorted_by_average(self):
        rows = stats.genre_averages()
        avgs = [r["avg"] for r in rows]
        self.assertEqual(avgs, sorted(avgs, reverse=True))
        comedy = next(r for r in rows if r["slug"] == "comedy")
        self.assertEqual((comedy["count"], comedy["avg"]), (2, 9.5))

    def test_genre_decade_matrix(self):
        matrix = stats.genre_decade_matrix()
        self.assertEqual(matrix["decades"], [1920, 1930])
        self.assertEqual(matrix["rows"][0]["slug"], "comedy")  # biggest total first
        comedy_1920 = matrix["rows"][0]["cells"][0]
        self.assertEqual((comedy_1920["avg"], comedy_1920["count"]), (9.5, 2))
        self.assertIsNone(matrix["rows"][0]["cells"][1])  # no 1930s comedies

    def test_people_for_role_threshold_split(self):
        table = stats.people_for_role("act", min_films=2)
        self.assertEqual([p["name"] for p in table["ranked"]], ["Charlie Chaplin"])
        self.assertEqual(table["rest"], [])
        table = stats.people_for_role("dir", min_films=2)
        self.assertEqual(table["ranked"], [])
        self.assertEqual(len(table["rest"]), 2)

    def test_people_for_role_averages(self):
        table = stats.people_for_role("act", min_films=1)
        chaplin = table["ranked"][0]
        self.assertEqual(chaplin["count"], 2)
        self.assertAlmostEqual(chaplin["avg"], 9.5)

    def test_person_roles(self):
        blocks = stats.person_roles(self.chaplin)
        self.assertEqual([b["role"] for b in blocks], ["dir", "act"])
        act = blocks[1]
        self.assertEqual(act["count"], 2)
        self.assertAlmostEqual(act["avg"], 9.5)

    def test_film_credits_grouped_in_role_order(self):
        blocks = stats.film_credits(self.kid)
        self.assertEqual([b["label"] for b in blocks], ["Director", "Actor"])
        self.assertEqual(blocks[1]["credits"][0].character, "Tramp")

    def test_same_year_films(self):
        titles = [f.title for f in stats.same_year_films(self.caligari)]
        self.assertEqual(titles, ["Way Down East", "Zorro"])
