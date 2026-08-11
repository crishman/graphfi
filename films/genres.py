"""Closed genre vocabulary.

Nothing outside this list can be added — otherwise in a year there will be
"noir", "Noir" and "film-noir" as three separate tags and every aggregation
falls apart. Edit here, then run `python manage.py seed_genres`.
"""

MAX_GENRES_PER_FILM = 3

GENRES = [
    ("adventure", "Adventure"),
    ("animation", "Animation"),
    ("comedy", "Comedy"),
    ("crime", "Crime"),
    ("documentary", "Documentary"),
    ("drama", "Drama"),
    ("fantasy", "Fantasy"),
    ("historical", "Historical"),
    ("horror", "Horror"),
    ("musical", "Musical"),
    ("mystery", "Mystery"),
    ("noir", "Noir"),
    ("romance", "Romance"),
    ("scifi", "Sci-Fi"),
    ("serial", "Serial episode"),
    ("spy", "Spy"),
    ("swashbuckler", "Swashbuckler"),
    ("thriller", "Thriller"),
    ("war", "War"),
    ("western", "Western"),
]

GENRE_SLUGS = {slug for slug, _ in GENRES}

# TMDB numeric genre ids -> our slugs. TMDB has no noir, serial or
# swashbuckler — those are set by hand only, which is expected: they are
# the author's own tagging, not somebody else's import. TMDB ids without
# a mapping (Action, Family, TV Movie) are skipped on purpose.
TMDB_GENRE_MAP = {
    12: "adventure",
    16: "animation",
    35: "comedy",
    80: "crime",
    99: "documentary",
    18: "drama",
    14: "fantasy",
    36: "historical",
    27: "horror",
    10402: "musical",
    9648: "mystery",
    10749: "romance",
    878: "scifi",
    53: "thriller",
    10752: "war",
    37: "western",
}
