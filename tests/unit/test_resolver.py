from django.test import SimpleTestCase

from films import resolver


def tmdb_payload(**overrides):
    payload = {
        "id": 19,
        "title": "Metropolis",
        "original_title": "Metropolis",
        "release_date": "1927-01-10",
        "imdb_id": "tt0017136",
        "runtime": 149,
        "poster_path": "/poster.jpg",
        "production_countries": [{"iso_3166_1": "DE", "name": "Germany"}],
        "genres": [
            {"id": 18, "name": "Drama"},
            {"id": 878, "name": "Science Fiction"},
            {"id": 28, "name": "Action"},        # unmapped on purpose
            {"id": 53, "name": "Thriller"},
            {"id": 36, "name": "History"},       # over the limit of 3
        ],
        "credits": {
            "cast": [
                {"id": i, "name": f"Actor {i}", "character": f"Char {i}",
                 "order": i, "profile_path": "/p.jpg" if i % 2 else None}
                for i in range(15)
            ],
            "crew": [
                {"id": 100, "name": "Fritz Lang", "job": "Director"},
                {"id": 101, "name": "Karl Freund", "job": "Director of Photography"},
                {"id": 102, "name": "Gottfried Huppertz", "job": "Original Music Composer"},
                {"id": 103, "name": "Thea von Harbou", "job": "Screenplay"},
                {"id": 103, "name": "Thea von Harbou", "job": "Writer"},
                {"id": 104, "name": "Erich Pommer", "job": "Producer"},
            ],
        },
    }
    payload.update(overrides)
    return payload


class FilmFromPayloadTests(SimpleTestCase):
    def test_basic_fields(self):
        data = resolver.film_from_payload(tmdb_payload())
        self.assertEqual(data.tmdb_id, 19)
        self.assertEqual(data.year, 1927)
        self.assertEqual(data.imdb_id, "tt0017136")
        self.assertEqual(data.runtime, 149)
        self.assertEqual(data.country, "Germany")
        self.assertEqual(data.poster_url, "https://image.tmdb.org/t/p/w342/poster.jpg")

    def test_genres_mapped_capped_and_unmapped_skipped(self):
        data = resolver.film_from_payload(tmdb_payload())
        # Action has no mapping; History would be 4th and is cut by the cap.
        self.assertEqual(data.genre_slugs, ["drama", "scifi", "thriller"])

    def test_cast_capped_at_twelve_with_billing(self):
        data = resolver.film_from_payload(tmdb_payload())
        actors = [c for c in data.credits if c.role == "act"]
        self.assertEqual(len(actors), 12)
        self.assertEqual(actors[0].billing, 0)
        self.assertEqual(actors[0].character, "Char 0")

    def test_crew_roles_mapped_and_deduplicated(self):
        data = resolver.film_from_payload(tmdb_payload())
        crew_roles = sorted(c.role for c in data.credits if c.role != "act")
        # Screenplay + Writer collapse into one writ; Producer is dropped.
        self.assertEqual(crew_roles, ["comp", "dir", "dop", "writ"])

    def test_person_photo_url_built_or_empty(self):
        data = resolver.film_from_payload(tmdb_payload())
        actors = [c.person for c in data.credits if c.role == "act"]
        self.assertEqual(actors[1].photo_url, "https://image.tmdb.org/t/p/w185/p.jpg")
        self.assertEqual(actors[0].photo_url, "")

    def test_missing_optional_fields(self):
        data = resolver.film_from_payload({
            "id": 7, "title": "Bare", "release_date": "", "credits": {},
        })
        self.assertEqual(data.year, None)
        self.assertEqual(data.poster_url, "")
        self.assertEqual(data.country, "")
        self.assertEqual(data.credits, [])
        self.assertEqual(data.genre_slugs, [])


class WikidataParseTests(SimpleTestCase):
    def binding(self, role, qid, label):
        return {
            "role": {"value": role},
            "person": {"value": f"http://www.wikidata.org/entity/{qid}"},
            "personLabel": {"value": label},
        }

    def test_grouped_by_role_and_deduplicated(self):
        payload = {"results": {"bindings": [
            self.binding("dop", "Q66333", "Karl Freund"),
            self.binding("dop", "Q66333", "Karl Freund"),
            self.binding("comp", "Q76483", "Gottfried Huppertz"),
        ]}}
        parsed = resolver.parse_wikidata_response(payload)
        self.assertEqual(sorted(parsed), ["comp", "dop"])
        self.assertEqual(len(parsed["dop"]), 1)
        self.assertEqual(parsed["dop"][0].wikidata_id, "Q66333")

    def test_unnamed_entities_and_unknown_roles_skipped(self):
        payload = {"results": {"bindings": [
            self.binding("comp", "Q123", "Q123"),      # label fell back to the Q-id
            self.binding("producer", "Q1", "Somebody"),  # role we do not track
        ]}}
        self.assertEqual(resolver.parse_wikidata_response(payload), {})

    def test_empty_response(self):
        self.assertEqual(resolver.parse_wikidata_response({}), {})


class GuardTests(SimpleTestCase):
    def test_empty_api_key_raises_before_any_network(self):
        with self.assertRaises(resolver.ResolverError):
            resolver.search_movie("Metropolis", 1927, "")

    def test_empty_imdb_id_short_circuits_wikidata(self):
        # Returns {} immediately: no sleep, no request.
        self.assertEqual(resolver.wikidata_credits(""), {})

    def test_sparql_query_contains_all_roles(self):
        query = resolver._wikidata_query("tt0017136")
        self.assertIn('"tt0017136"', query)
        for prop in ("P57", "P344", "P86", "P58"):
            self.assertIn(f"wdt:{prop}", query)
