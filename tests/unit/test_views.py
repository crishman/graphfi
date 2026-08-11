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

    def test_person_detail(self):
        response = self.client.get(f"/person/{self.chaplin.pk}/")
        self.assertContains(response, "The Kid")

    def test_empty_database_renders_everywhere(self):
        Credit.objects.all().delete()
        Person.objects.all().delete()
        Film.objects.all().delete()
        for url in ("/", "/?axis=watched", "/films/", "/people/", "/add/"):
            self.assertEqual(self.client.get(url).status_code, 200, url)


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
