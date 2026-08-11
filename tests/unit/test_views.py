import datetime

from django.core.management import call_command
from django.test import TestCase

from films.models import Credit, Film, Genre, Person


class ViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_genres", verbosity=0)
        g = {x.slug: x for x in Genre.objects.all()}
        cls.kid = Film.objects.create(
            title="The Kid", year=1921, rating=9, watched_at=datetime.date(2026, 1, 11)
        )
        cls.kid.genres.set([g["comedy"], g["drama"]])
        cls.zorro = Film.objects.create(title="Zorro", year=1920, rating=7)
        cls.bare = Film.objects.create(title="Bare <Film> & Co", year=1929)
        cls.chaplin = Person.objects.create(name="Charlie Chaplin")
        Credit.objects.create(film=cls.kid, person=cls.chaplin, role="dir")

    def test_profile_renders(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<svg", count=5)

    def test_profile_axis_toggle(self):
        response = self.client.get("/?axis=watched")
        self.assertContains(response, "switch to release year")

    def test_film_list_and_filters(self):
        self.assertContains(self.client.get("/films/"), "The Kid")
        response = self.client.get("/films/?year=1920")
        self.assertContains(response, "Zorro")
        self.assertNotContains(response, "The Kid")
        response = self.client.get("/films/?genre=comedy")
        self.assertContains(response, "The Kid")
        self.assertNotContains(response, "Zorro")
        response = self.client.get("/films/?unrated=1")
        self.assertContains(response, "Bare")
        self.assertNotContains(response, "Zorro")
        response = self.client.get("/films/?q=zor")
        self.assertContains(response, "Zorro")

    def test_film_list_sorting(self):
        response = self.client.get("/films/?sort=rating")
        body = response.content.decode()
        self.assertLess(body.index("Zorro"), body.index("The Kid"))

    def test_film_detail_with_unsafe_title(self):
        response = self.client.get(f"/film/{self.bare.pk}/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Bare &lt;Film&gt; &amp; Co")

    def test_film_detail_same_year_block(self):
        Film.objects.create(title="Way Down East", year=1920)
        response = self.client.get(f"/film/{self.zorro.pk}/")
        self.assertContains(response, "Way Down East")

    def test_film_detail_404(self):
        self.assertEqual(self.client.get("/film/99999/").status_code, 404)

    def test_people_role_tabs(self):
        response = self.client.get("/people/?role=dir")
        self.assertContains(response, "Charlie Chaplin")
        self.assertEqual(self.client.get("/people/?role=hack").status_code, 404)

    def test_people_below_threshold_shown_open_when_no_ranked(self):
        # Chaplin has one rated film — below the default threshold of 3 —
        # so the ranked table is empty and the rest list must be visible.
        response = self.client.get("/people/?role=dir")
        self.assertContains(response, "<details open>", html=False)
        self.assertContains(response, "everyone so far is in the list below")

    def test_profile_shows_below_threshold_people(self):
        response = self.client.get("/")
        self.assertContains(response, "still below the ranking threshold")
        self.assertContains(response, "Charlie Chaplin")

    def test_person_detail(self):
        response = self.client.get(f"/person/{self.chaplin.pk}/")
        self.assertContains(response, "The Kid")

    def test_empty_database_renders_everywhere(self):
        Credit.objects.all().delete()
        Person.objects.all().delete()
        Film.objects.all().delete()
        for url in ("/", "/?axis=watched", "/films/", "/people/", "/add/"):
            self.assertEqual(self.client.get(url).status_code, 200, url)


class RateFilmTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth.models import User

        User.objects.create_superuser("owner", "", "pass")
        cls.film = Film.objects.create(title="The General", year=1926)

    def login(self):
        self.client.login(username="owner", password="pass")

    def test_widget_hidden_from_anonymous(self):
        response = self.client.get(f"/film/{self.film.pk}/")
        self.assertNotContains(response, "rate-form")

    def test_widget_shown_to_staff(self):
        self.login()
        response = self.client.get(f"/film/{self.film.pk}/")
        self.assertContains(response, "rate-form")
        self.assertContains(response, 'name="rating" value="10"')

    def test_anonymous_post_redirects_to_login(self):
        response = self.client.post(f"/film/{self.film.pk}/rate/", {"rating": "9"})
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response.url)
        self.film.refresh_from_db()
        self.assertIsNone(self.film.rating)

    def test_rating_saved_with_default_date(self):
        self.login()
        response = self.client.post(f"/film/{self.film.pk}/rate/", {"rating": "9"})
        self.assertEqual(response.status_code, 302)
        self.film.refresh_from_db()
        self.assertEqual(self.film.rating, 9)
        self.assertIsNotNone(self.film.watched_at)

    def test_rating_saved_with_explicit_date(self):
        self.login()
        self.client.post(f"/film/{self.film.pk}/rate/",
                         {"rating": "7", "watched_at": "2026-08-10"})
        self.film.refresh_from_db()
        self.assertEqual(self.film.rating, 7)
        self.assertEqual(str(self.film.watched_at), "2026-08-10")

    def test_keep_updates_date_only(self):
        Film.objects.filter(pk=self.film.pk).update(rating=8)
        self.login()
        self.client.post(f"/film/{self.film.pk}/rate/",
                         {"rating": "keep", "watched_at": "2026-08-01"})
        self.film.refresh_from_db()
        self.assertEqual(self.film.rating, 8)
        self.assertEqual(str(self.film.watched_at), "2026-08-01")

    def test_clear_removes_rating_keeps_date(self):
        import datetime

        Film.objects.filter(pk=self.film.pk).update(
            rating=8, watched_at=datetime.date(2026, 8, 1))
        self.login()
        self.client.post(f"/film/{self.film.pk}/rate/", {"rating": "clear"})
        self.film.refresh_from_db()
        self.assertIsNone(self.film.rating)
        self.assertEqual(str(self.film.watched_at), "2026-08-01")

    def test_garbage_rating_ignored(self):
        self.login()
        for raw in ("0", "11", "9.5", "ten"):
            self.client.post(f"/film/{self.film.pk}/rate/", {"rating": raw})
        self.film.refresh_from_db()
        self.assertIsNone(self.film.rating)

    def test_bad_date_does_not_break_save(self):
        self.login()
        self.client.post(f"/film/{self.film.pk}/rate/",
                         {"rating": "6", "watched_at": "not-a-date"})
        self.film.refresh_from_db()
        self.assertEqual(self.film.rating, 6)


class BulkAddViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_genres", verbosity=0)

    def test_get_form(self):
        self.assertEqual(self.client.get("/add/").status_code, 200)

    def test_preview_shows_statuses_without_saving(self):
        response = self.client.post(
            "/add/", {"text": "Nosferatu | 1922 | 8", "action": "preview"}
        )
        self.assertContains(response, "new")
        self.assertEqual(Film.objects.count(), 0)

    def test_save_applies_and_redirects(self):
        response = self.client.post(
            "/add/", {"text": "Nosferatu | 1922 | 8 | | horror", "action": "save"}
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Film.objects.count(), 1)

    def test_broken_text_reports_lines_and_saves_nothing(self):
        text = "Good | 1922\nbroken\nAlso Good | 1923 | 99"
        response = self.client.post("/add/", {"text": text, "action": "save"})
        self.assertEqual(response.status_code, 200)  # stays on the page
        self.assertContains(response, "line 2")
        self.assertContains(response, "line 3")
        self.assertEqual(Film.objects.count(), 0)
