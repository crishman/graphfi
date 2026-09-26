import io
from unittest import mock

from django.core.management import call_command
from django.test import TestCase, override_settings

from films import resolver
from films.management.commands.resolve import Command
from films.models import Credit, Film, Genre, Person
from tests.unit.test_resolver import tmdb_payload


def film_data():
    return resolver.film_from_payload(tmdb_payload())


class ResolveCommandTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_genres", verbosity=0)

    def setUp(self):
        self.film = Film.objects.create(title="Metropolis", year=1927, rating=9)
        self.command = Command()
        self.command.stdout = io.StringIO()
        self.command.stderr = io.StringIO()

    def resolve(self):
        with mock.patch.object(resolver, "search_movie",
                               return_value=[resolver.Candidate(19, "Metropolis", "Metropolis", 1927)]), \
             mock.patch.object(resolver, "fetch_movie", return_value=film_data()), \
             mock.patch.object(resolver, "wikidata_credits", return_value={}):
            return self.command.resolve_film(self.film, "fake-key", auto=True)

    def test_fills_empty_fields(self):
        self.assertTrue(self.resolve())
        self.film.refresh_from_db()
        self.assertEqual(self.film.tmdb_id, 19)
        self.assertEqual(self.film.imdb_id, "tt0017136")
        self.assertEqual(self.film.runtime, 149)
        self.assertEqual(self.film.country, "Germany")
        self.assertEqual(
            sorted(self.film.genres.values_list("slug", flat=True)),
            ["drama", "scifi", "thriller"],
        )
        self.assertEqual(self.film.credits.count(), 16)

    def test_never_overwrites_owner_edits(self):
        self.film.country = "Weimar Republic"
        self.film.save()
        self.film.genres.set(Genre.objects.filter(slug="scifi"))
        self.resolve()
        self.film.refresh_from_db()
        self.assertEqual(self.film.rating, 9)
        self.assertEqual(self.film.country, "Weimar Republic")
        self.assertEqual(
            list(self.film.genres.values_list("slug", flat=True)), ["scifi"]
        )

    def test_force_rerun_creates_no_duplicates(self):
        self.resolve()
        people = Person.objects.count()
        credits = Credit.objects.count()
        self.resolve()  # simulates resolve --force running again
        self.assertEqual(Person.objects.count(), people)
        self.assertEqual(Credit.objects.count(), credits)

    def test_existing_person_matched_by_name_and_backfilled(self):
        lang = Person.objects.create(name="Fritz Lang")
        self.resolve()
        lang.refresh_from_db()
        self.assertEqual(lang.tmdb_id, 100)
        self.assertEqual(Person.objects.filter(name="Fritz Lang").count(), 1)

    def test_gender_stored_and_filled_but_never_overwritten(self):
        blank = Person.objects.create(name="Actor 1", tmdb_id=1)
        edited = Person.objects.create(name="Actor 2", tmdb_id=2, gender=Person.Gender.FEMALE)
        self.resolve()
        blank.refresh_from_db()
        edited.refresh_from_db()
        self.assertEqual(blank.gender, Person.Gender.FEMALE)       # filled from TMDB's 1
        self.assertEqual(edited.gender, Person.Gender.FEMALE)      # TMDB says 2; owner wins
        self.assertEqual(Person.objects.get(tmdb_id=3).gender, Person.Gender.NON_BINARY)
        self.assertIsNone(Person.objects.get(tmdb_id=4).gender)    # TMDB 0

    def test_linked_film_refreshed_by_stored_id_never_searched(self):
        self.film.tmdb_id = 19
        self.film.save()
        search = mock.Mock()
        fetch = mock.Mock(return_value=film_data())
        with mock.patch.object(resolver, "search_movie", search), \
             mock.patch.object(resolver, "fetch_movie", fetch), \
             mock.patch.object(resolver, "wikidata_credits", return_value={}):
            self.assertTrue(self.command.resolve_film(self.film, "fake-key", auto=True))
        search.assert_not_called()
        fetch.assert_called_once_with(19, "fake-key")
        self.film.refresh_from_db()
        self.assertEqual(self.film.tmdb_id, 19)
        self.assertEqual(self.film.credits.count(), 16)

    def test_auto_skips_on_year_mismatch(self):
        with mock.patch.object(resolver, "search_movie",
                               return_value=[resolver.Candidate(19, "Metropolis", "Metropolis", 2001)]):
            self.assertFalse(self.command.resolve_film(self.film, "fake-key", auto=True))
        self.film.refresh_from_db()
        self.assertIsNone(self.film.tmdb_id)

    def test_tmdb_id_clash_skips(self):
        Film.objects.create(title="Other", year=1927, tmdb_id=19)
        self.assertFalse(self.resolve())
        self.film.refresh_from_db()
        self.assertIsNone(self.film.tmdb_id)

    def test_wikidata_tops_up_only_missing_roles(self):
        wd = {
            "dir": [resolver.PersonData(name="Someone New", wikidata_id="Q1")],
            "dop": [resolver.PersonData(name="Extra Dop", wikidata_id="Q2")],
        }
        data = film_data()
        data.credits = [c for c in data.credits if c.role != "dop"]  # TMDB gave no dop
        with mock.patch.object(resolver, "search_movie",
                               return_value=[resolver.Candidate(19, "Metropolis", "Metropolis", 1927)]), \
             mock.patch.object(resolver, "fetch_movie", return_value=data), \
             mock.patch.object(resolver, "wikidata_credits", return_value=wd):
            self.command.resolve_film(self.film, "fake-key", auto=True)
        # dop came from Wikidata; dir already existed from TMDB and was left alone.
        self.assertTrue(Credit.objects.filter(film=self.film, role="dop",
                                              person__name="Extra Dop").exists())
        self.assertFalse(Person.objects.filter(name="Someone New").exists())

    def test_wikidata_failure_does_not_break_resolve(self):
        data = film_data()
        data.credits = [c for c in data.credits if c.role == "act"]  # all crew missing
        wikidata = mock.Mock(side_effect=resolver.ResolverError("boom"))
        with mock.patch.object(resolver, "search_movie",
                               return_value=[resolver.Candidate(19, "Metropolis", "Metropolis", 1927)]), \
             mock.patch.object(resolver, "fetch_movie", return_value=data), \
             mock.patch.object(resolver, "wikidata_credits", wikidata):
            self.assertTrue(self.command.resolve_film(self.film, "fake-key", auto=True))
        wikidata.assert_called_once()  # the failing path really ran
        self.film.refresh_from_db()
        self.assertEqual(self.film.tmdb_id, 19)


@override_settings(TMDB_API_KEY="fake-key")
class FillGenderCommandTests(TestCase):
    def setUp(self):
        self.linked = Film.objects.create(title="Metropolis", year=1927, tmdb_id=19)
        self.unlinked = Film.objects.create(title="Unlinked", year=1927)
        self.blank = Person.objects.create(name="Actor 1", tmdb_id=1)
        self.edited = Person.objects.create(name="Actor 2", tmdb_id=2, gender=Person.Gender.FEMALE)
        self.stray = Person.objects.create(name="Nobody", tmdb_id=999)
        for person in (self.blank, self.edited):
            Credit.objects.create(film=self.linked, person=person, role="act")
        Credit.objects.create(film=self.unlinked, person=self.stray, role="act")

    def run_command(self, fetch):
        out = io.StringIO()
        with mock.patch.object(resolver, "fetch_movie", fetch):
            call_command("fill_gender", stdout=out, stderr=io.StringIO())
        return out.getvalue()

    def test_fills_only_empty_genders_and_adds_nothing(self):
        credits = Credit.objects.count()
        people = Person.objects.count()
        fetch = mock.Mock(return_value=film_data())
        out = self.run_command(fetch)
        fetch.assert_called_once_with(19, "fake-key")    # the unlinked film is never fetched
        self.blank.refresh_from_db()
        self.edited.refresh_from_db()
        self.assertEqual(self.blank.gender, Person.Gender.FEMALE)
        self.assertEqual(self.edited.gender, Person.Gender.FEMALE)
        self.assertEqual(Credit.objects.count(), credits)
        self.assertEqual(Person.objects.count(), people)
        self.assertIn("Filled gender for 1 people; 1 actors still have none", out)

    def test_films_with_every_gender_known_are_skipped(self):
        self.blank.gender = Person.Gender.MALE
        self.blank.save()
        fetch = mock.Mock(return_value=film_data())
        self.run_command(fetch)
        fetch.assert_not_called()

    def test_tmdb_failure_is_reported_not_fatal(self):
        out = self.run_command(mock.Mock(side_effect=resolver.ResolverError("boom")))
        self.assertIn("1 films failed", out)
        self.blank.refresh_from_db()
        self.assertIsNone(self.blank.gender)
