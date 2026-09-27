from django.test import SimpleTestCase

from films import resolver


def tv_payload(**overrides):
    payload = {
        "id": 1920,
        "name": "Twin Peaks",
        "original_name": "Twin Peaks",
        "first_air_date": "1990-04-08",
        "last_air_date": "2017-09-03",
        "type": "Scripted",
        "poster_path": "/tp.jpg",
        "production_countries": [{"iso_3166_1": "US", "name": "United States of America"}],
        "genres": [
            {"id": 18, "name": "Drama"},
            {"id": 10765, "name": "Sci-Fi & Fantasy"},
            {"id": 10762, "name": "Kids"},          # unmapped on purpose
            {"id": 9648, "name": "Mystery"},
            {"id": 80, "name": "Crime"},            # over the limit of 3
        ],
        "created_by": [
            {"id": 5, "name": "Mark Frost", "gender": 2, "profile_path": None},
            {"id": 6, "name": "David Lynch", "gender": 2, "profile_path": "/dl.jpg"},
        ],
        "external_ids": {"imdb_id": "tt0098936", "wikidata_id": "Q2085"},
        "seasons": [
            {"season_number": 0, "name": "Specials", "air_date": "1989-12-08", "episode_count": 130},
            {"season_number": 1, "name": "Season 1", "air_date": "1990-04-08", "episode_count": 8,
             "poster_path": "/s1.jpg"},
            {"season_number": 2, "name": "Season 2", "air_date": "1990-09-30", "episode_count": 22},
            {"season_number": 3, "name": "The Return", "air_date": "2017-05-21", "episode_count": 18},
        ],
    }
    payload.update(overrides)
    return payload


def season_credits_payload():
    return {
        "cast": [
            {"id": 10, "name": "Kyle MacLachlan", "gender": 2, "order": 0, "total_episode_count": 8,
             "roles": [{"character": "Dale Cooper", "episode_count": 8}]},
            {"id": 11, "name": "Sheryl Lee", "gender": 1, "order": 3, "total_episode_count": 4,
             "roles": [{"character": "Laura Palmer", "episode_count": 1},
                       {"character": "Maddy Ferguson", "episode_count": 3}]},
            {"id": 12, "name": "A Guest", "gender": 1, "order": 1, "total_episode_count": 3,
             "roles": [{"character": "Guest", "episode_count": 3}]},
        ],
        "crew": [
            {"id": 6, "name": "David Lynch", "gender": 2,
             "jobs": [{"job": "Director", "episode_count": 2}, {"job": "Writer", "episode_count": 3}]},
            {"id": 20, "name": "Tina Rathborne", "gender": 1,
             "jobs": [{"job": "Director", "episode_count": 1}]},
            {"id": 21, "name": "A Producer", "gender": 2,
             "jobs": [{"job": "Producer", "episode_count": 8}]},
        ],
    }


class SeriesFromPayloadTests(SimpleTestCase):
    def test_basic_fields(self):
        data = resolver.series_from_payload(tv_payload())
        self.assertEqual((data.tmdb_id, data.title, data.first_year, data.last_year),
                         (1920, "Twin Peaks", 1990, 2017))
        self.assertEqual(data.tv_type, "Scripted")
        self.assertEqual((data.imdb_id, data.wikidata_id), ("tt0098936", "Q2085"))
        self.assertEqual(data.country, "United States of America")
        self.assertEqual(data.poster_url, "https://image.tmdb.org/t/p/w342/tp.jpg")

    def test_tv_genres_mapped_capped_and_unmapped_skipped(self):
        data = resolver.series_from_payload(tv_payload())
        # Kids has no slug; Crime would be the 4th and is cut by the cap.
        self.assertEqual(data.genre_slugs, ["drama", "scifi", "mystery"])

    def test_specials_left_out_and_each_season_keeps_its_year(self):
        data = resolver.series_from_payload(tv_payload())
        self.assertEqual([(s.number, s.year, s.episode_count) for s in data.seasons],
                         [(1, 1990, 8), (2, 1990, 22), (3, 2017, 18)])
        self.assertEqual(data.seasons[2].name, "The Return")
        self.assertEqual(data.seasons[0].poster_url, "https://image.tmdb.org/t/p/w342/s1.jpg")
        self.assertEqual(data.seasons[1].poster_url, "")

    def test_creators_with_gender(self):
        data = resolver.series_from_payload(tv_payload())
        self.assertEqual([(p.name, p.tmdb_id, p.gender) for p in data.creators],
                         [("Mark Frost", 5, 2), ("David Lynch", 6, 2)])

    def test_missing_optional_fields(self):
        data = resolver.series_from_payload({"id": 1, "name": "Bare"})
        self.assertEqual((data.first_year, data.seasons, data.creators, data.genre_slugs),
                         (None, [], [], []))


class SeasonCreditsTests(SimpleTestCase):
    def test_cast_is_people_in_half_the_episodes(self):
        credits = resolver.season_credits_from_payload(season_credits_payload(), episode_count=8)
        cast = [c for c in credits if c.role == "act"]
        self.assertEqual([c.person.name for c in cast], ["Kyle MacLachlan", "Sheryl Lee"])
        self.assertEqual(cast[0].episodes, 8)
        self.assertEqual(cast[0].person.gender, 2)
        self.assertEqual(cast[1].character, "Maddy Ferguson")   # the part with most episodes

    def test_every_episode_director_with_episode_count(self):
        credits = resolver.season_credits_from_payload(season_credits_payload(), episode_count=8)
        directors = {c.person.name: c.episodes for c in credits if c.role == "dir"}
        self.assertEqual(directors, {"David Lynch": 2, "Tina Rathborne": 1})

    def test_unknown_episode_count_falls_back_to_the_longest_run(self):
        credits = resolver.season_credits_from_payload(season_credits_payload(), episode_count=None)
        self.assertEqual([c.person.name for c in credits if c.role == "act"],
                         ["Kyle MacLachlan", "Sheryl Lee"])

    def test_empty_payload(self):
        self.assertEqual(resolver.season_credits_from_payload({}, episode_count=10), [])
