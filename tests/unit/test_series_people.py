from django.core.management import call_command
from django.test import TestCase

from films import stats
from films.models import Credit, Film, Person, Season, SeasonCredit, Series


class SeriesPeopleTests(TestCase):
    """The TV tab for actors and directors: a series counts once, like a
    film, and the film tables never see a season."""

    @classmethod
    def setUpTestData(cls):
        call_command("seed_genres", verbosity=0)
        P = Person.Gender

        def series(title, year, ratings):
            s = Series.objects.create(title=title, first_year=year)
            return s, [Season.objects.create(series=s, number=i + 1, year=year + i, rating=r)
                       for i, r in enumerate(ratings)]

        cls.lucy, cls.lucy_seasons = series("I Love Lucy", 1951, [10, 10, 4])
        cls.zone, cls.zone_seasons = series("The Twilight Zone", 1959, [6])
        cls.peaks, cls.peaks_seasons = series("Twin Peaks", 1990, [9, None])
        cls.ball = Person.objects.create(name="Lucille Ball", gender=P.FEMALE)
        cls.serling = Person.objects.create(name="Rod Serling", gender=P.MALE)
        cls.lynch = Person.objects.create(name="David Lynch", gender=P.MALE)
        for season in cls.lucy_seasons:
            SeasonCredit.objects.create(season=season, person=cls.ball, role="act")
        SeasonCredit.objects.create(season=cls.zone_seasons[0], person=cls.ball, role="act")
        SeasonCredit.objects.create(season=cls.zone_seasons[0], person=cls.serling, role="act")
        SeasonCredit.objects.create(season=cls.zone_seasons[0], person=cls.serling, role="crea")
        for season in cls.peaks_seasons:
            SeasonCredit.objects.create(season=season, person=cls.lynch, role="dir", episodes=2)
        SeasonCredit.objects.create(season=cls.peaks_seasons[1], person=cls.serling, role="act")
        # A film, to prove the film tables ignore TV.
        cls.film = Film.objects.create(title="Eraserhead", year=1977, runtime=89, rating=8)
        Credit.objects.create(film=cls.film, person=cls.lynch, role="dir")

    @staticmethod
    def by_name(table):
        return {e["name"]: e for e in table["ranked"] + table["rest"]}

    def test_tabs_put_tv_after_features_for_actors_and_directors_only(self):
        self.assertEqual([f for f, _ in stats.people_tabs("act")], ["feature", "tv", "short", "animation"])
        self.assertEqual([f for f, _ in stats.people_tabs("dir")], ["feature", "tv", "short", "animation"])
        self.assertEqual([f for f, _ in stats.people_tabs("dop")], ["feature", "short", "animation"])

    def test_series_count_once_and_average_per_series(self):
        table = stats.series_people_for_role("act", min_films=1)
        ball = self.by_name(table)["Lucille Ball"]
        self.assertEqual(ball["count"], 2)
        # Lucy averages 8 over its three seasons, the Zone 6: (8 + 6) / 2,
        # not the 7.5 that counting seasons would give.
        self.assertAlmostEqual(ball["avg"], 7)

    def test_unrated_seasons_do_not_count(self):
        serling = self.by_name(stats.series_people_for_role("act", min_films=1))["Rod Serling"]
        self.assertEqual(serling["count"], 1)       # his Twin Peaks season is unrated
        lynch = self.by_name(stats.series_people_for_role("dir", min_films=1))["David Lynch"]
        self.assertEqual((lynch["count"], lynch["avg"]), (1, 9))

    def test_tv_table_is_one_mixed_table(self):
        (table,) = stats.people_tables("act", "tv")
        self.assertEqual((table["title"], table["unit"], table["form"]), ("Actors", "series", "tv"))
        self.assertEqual(set(self.by_name(table)), {"Lucille Ball", "Rod Serling"})

    def test_threshold_applies_to_series(self):
        table = stats.series_people_for_role("act")         # default threshold 3
        self.assertEqual(table["ranked"], [])
        self.assertEqual(len(table["rest"]), 2)

    def test_film_tables_never_see_seasons(self):
        directors = self.by_name(stats.people_for_role("dir", min_films=1, form="feature"))
        self.assertEqual(directors["David Lynch"]["count"], 1)       # Eraserhead only
        actors = self.by_name(stats.people_for_role("act", min_films=1))
        self.assertNotIn("Lucille Ball", actors)
        self.assertEqual(stats.overview()["total"], 1)

    def test_person_series_roles(self):
        blocks = {b["role"]: b for b in stats.person_series_roles(self.ball)}
        self.assertEqual(blocks["act"]["label"], "Actress")
        self.assertEqual([(r["series"].title, r["seasons"], r["avg"]) for r in blocks["act"]["rows"]],
                         [("I Love Lucy", "S1–3", 8), ("The Twilight Zone", "S1", 6)])
        self.assertAlmostEqual(blocks["act"]["avg"], 7)
        roles = [b["role"] for b in stats.person_series_roles(self.serling)]
        self.assertEqual(roles, ["crea", "act"])


class SeriesPeopleViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        series = Series.objects.create(title="I Love Lucy", first_year=1951)
        season = Season.objects.create(series=series, number=1, year=1951, rating=8)
        cls.ball = Person.objects.create(name="Lucille Ball", gender=Person.Gender.FEMALE)
        SeasonCredit.objects.create(season=season, person=cls.ball, role="act", character="Lucy Ricardo")
        film = Film.objects.create(title="The Kid", year=1921, rating=9)
        cls.chaplin = Person.objects.create(name="Charlie Chaplin", gender=Person.Gender.MALE)
        Credit.objects.create(film=film, person=cls.chaplin, role="act")

    def test_tv_tab_page(self):
        response = self.client.get("/people/?role=act&form=tv")
        self.assertContains(response, "Actors — TV")
        self.assertContains(response, "<th class=\"num-col\">Series</th>", html=False)
        self.assertContains(response, "Fewer than 3 rated series")
        self.assertContains(response, "Lucille Ball")
        self.assertNotContains(response, "Charlie Chaplin")
        self.assertNotContains(response, "Actresses")
        self.assertNotContains(response, "In neither table")

    def test_form_row_links(self):
        response = self.client.get("/people/?role=act")
        self.assertContains(response, "?role=act&amp;form=tv")
        response = self.client.get("/people/?role=dir&form=tv")
        self.assertEqual(response.status_code, 200)
        response = self.client.get("/people/?role=dop")
        self.assertNotContains(response, "form=tv")
        self.assertEqual(self.client.get("/people/?role=dop&form=tv").status_code, 404)

    def test_profile_links_tv_from_the_features_block(self):
        self.assertContains(self.client.get("/"), "/people/?role=act&amp;form=tv")

    def test_person_page_tv_block(self):
        response = self.client.get(f"/person/{self.ball.pk}/")
        self.assertContains(response, "As actress · TV")
        self.assertContains(response, "Lucy Ricardo")
        self.assertNotContains(response, "No credits recorded")
        response = self.client.get(f"/person/{self.chaplin.pk}/")
        self.assertNotContains(response, "· TV")
