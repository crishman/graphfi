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


class FilmFormTests(TestCase):
    """Slicing the actor / director / cinematographer tables by film form.
    Fixtures sit on the boundaries: 40 minutes is a short, 41 a feature,
    animation wins regardless of length, no runtime means feature."""

    @classmethod
    def setUpTestData(cls):
        call_command("seed_genres", verbosity=0)
        g = {x.slug: x for x in Genre.objects.all()}

        def film(title, year, runtime, rating, genres=()):
            obj = Film.objects.create(title=title, year=year, runtime=runtime, rating=rating)
            obj.genres.set([g[s] for s in genres])
            return obj

        cls.sherlock = film("Sherlock Jr.", 1924, 45, 8, ["comedy"])
        cls.general = film("The General", 1926, 41, 9, ["comedy"])    # boundary: feature
        cls.one_week = film("One Week", 1920, 20, 7, ["comedy"])
        cls.cops = film("Cops", 1922, 40, 6, ["comedy"])              # boundary: short
        cls.willie = film("Steamboat Willie", 1928, 8, 7, ["animation", "comedy"])
        cls.snow_white = film("Snow White", 1937, 83, 8, ["animation", "fantasy"])
        cls.no_runtime = film("Unknown Length", 1925, None, 5, ["drama"])
        cls.unrated_short = film("Unrated Short", 1921, 15, None, ["comedy"])

        cls.keaton = Person.objects.create(name="Buster Keaton")
        cls.disney = Person.objects.create(name="Walt Disney")
        cls.dop = Person.objects.create(name="Elgin Lessley")
        for f in (cls.sherlock, cls.general, cls.one_week, cls.cops, cls.unrated_short):
            Credit.objects.create(film=f, person=cls.keaton, role="act")
            Credit.objects.create(film=f, person=cls.keaton, role="dir")
            Credit.objects.create(film=f, person=cls.dop, role="dop")
        for f in (cls.willie, cls.snow_white):
            Credit.objects.create(film=f, person=cls.disney, role="act", character="Mickey (voice)")
            Credit.objects.create(film=f, person=cls.disney, role="dir")
        Credit.objects.create(film=cls.no_runtime, person=cls.keaton, role="act")

    def test_film_form_rule(self):
        self.assertEqual(stats.film_form(self.general), "feature")
        self.assertEqual(stats.film_form(self.cops), "short")
        self.assertEqual(stats.film_form(self.willie), "animation")
        self.assertEqual(stats.film_form(self.snow_white), "animation")
        self.assertEqual(stats.film_form(self.no_runtime), "feature")

    def test_films_of_form_partitions_and_agrees_with_film_form(self):
        seen = {}
        for form in stats.FORM_ORDER:
            for film in stats.films_of_form(form):
                self.assertNotIn(film.pk, seen, f"{film} in two forms")
                seen[film.pk] = form
        self.assertEqual(set(seen), set(Film.objects.values_list("pk", flat=True)))
        for film in Film.objects.prefetch_related("genres"):
            self.assertEqual(stats.film_form(film), seen[film.pk], film.title)

    def test_people_for_role_sliced_by_form(self):
        by_name = lambda table: {p["name"]: p for p in table["ranked"] + table["rest"]}

        features = by_name(stats.people_for_role("act", min_films=1, form="feature"))
        self.assertEqual(features["Buster Keaton"]["count"], 3)   # 45, 41, no runtime
        self.assertAlmostEqual(features["Buster Keaton"]["avg"], (8 + 9 + 5) / 3)
        self.assertNotIn("Walt Disney", features)

        shorts = by_name(stats.people_for_role("act", min_films=1, form="short"))
        self.assertEqual(shorts["Buster Keaton"]["count"], 2)     # 20, 40; unrated short excluded
        self.assertAlmostEqual(shorts["Buster Keaton"]["avg"], 6.5)
        self.assertNotIn("Walt Disney", shorts)

        animation = by_name(stats.people_for_role("dir", min_films=1, form="animation"))
        self.assertEqual(list(animation), ["Walt Disney"])
        self.assertEqual(animation["Walt Disney"]["count"], 2)

        dops = by_name(stats.people_for_role("dop", min_films=1, form="short"))
        self.assertEqual(dops["Elgin Lessley"]["count"], 2)

    def test_people_for_role_without_form_counts_everything(self):
        table = stats.people_for_role("act", min_films=1)
        keaton = next(p for p in table["ranked"] if p["name"] == "Buster Keaton")
        self.assertEqual(keaton["count"], 5)
        self.assertEqual(table["form"], None)
        self.assertEqual(table["forms"], [])

    def test_people_for_role_form_metadata(self):
        table = stats.people_for_role("act", form="short")
        self.assertEqual(table["form_label"], "Shorts")
        self.assertEqual([f for f, _ in table["forms"]], ["feature", "short", "animation"])

    def test_film_credits_labels_cartoon_cast_as_voices(self):
        labels = {b["role"]: b["label"] for b in stats.film_credits(self.willie)}
        self.assertEqual(labels["act"], "Voice actor")
        self.assertEqual(labels["dir"], "Director")
        labels = {b["role"]: b["label"] for b in stats.film_credits(self.sherlock)}
        self.assertEqual(labels["act"], "Actor")

    def test_person_roles_form_breakdown(self):
        blocks = {b["role"]: b for b in stats.person_roles(self.keaton)}
        forms = {f["form"]: f for f in blocks["act"]["forms"]}
        self.assertEqual(set(forms), {"feature", "short"})
        self.assertEqual(forms["feature"]["count"], 3)
        self.assertEqual(forms["short"]["count"], 3)         # the unrated short counts as a film
        self.assertAlmostEqual(forms["short"]["avg"], 6.5)   # but not toward the average
        # Disney spans one form only — no breakdown line.
        blocks = {b["role"]: b for b in stats.person_roles(self.disney)}
        self.assertEqual(blocks["act"]["forms"], [])
