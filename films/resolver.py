"""TMDB + Wikidata metadata resolution.

Deliberately Django-free: the module is testable and reusable on its own.
It returns dataclasses, not models — turning them into database rows is
the `resolve` command's job.

Legal constraints baked in: images are never downloaded, only CDN URLs are
passed along; metadata comes from the TMDB API and Wikidata only.
"""

import time
from dataclasses import dataclass, field

import requests

from .genres import MAX_GENRES_PER_FILM, TMDB_GENRE_MAP

TMDB_API = "https://api.themoviedb.org/3"
TMDB_IMAGES = "https://image.tmdb.org/t/p"
WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"
USER_AGENT = "graphfi/1.0 (personal film journal)"
TIMEOUT = 15

# TMDB crew job names -> our role slugs (same values as Credit.Role).
CREW_JOBS = {
    "Director": "dir",
    "Original Music Composer": "comp",
    "Music": "comp",
    "Director of Photography": "dop",
    "Screenplay": "writ",
    "Writer": "writ",
}
CAST_LIMIT = 12

# Wikidata properties -> role slugs, for the post-TMDB fill-in.
WIKIDATA_ROLES = {
    "P57": "dir",
    "P344": "dop",
    "P86": "comp",
    "P58": "writ",
}


class ResolverError(Exception):
    pass


@dataclass
class PersonData:
    name: str
    original_name: str = ""
    tmdb_id: int | None = None
    wikidata_id: str = ""
    photo_url: str = ""


@dataclass
class CreditData:
    person: PersonData
    role: str
    character: str = ""
    billing: int | None = None


@dataclass
class Candidate:
    tmdb_id: int
    title: str
    original_title: str
    year: int | None


@dataclass
class FilmData:
    tmdb_id: int
    title: str
    original_title: str = ""
    year: int | None = None
    imdb_id: str = ""
    poster_url: str = ""
    runtime: int | None = None
    country: str = ""
    genre_slugs: list = field(default_factory=list)
    credits: list = field(default_factory=list)


def _tmdb_get(path, api_key, **params):
    if not api_key:
        raise ResolverError("TMDB_API_KEY is empty — set it in the environment.")
    params["api_key"] = api_key
    try:
        response = requests.get(
            f"{TMDB_API}{path}",
            params=params,
            headers={"User-Agent": USER_AGENT},
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        raise ResolverError(f"TMDB request failed: {exc}") from exc


def _release_year(release_date):
    if release_date and len(release_date) >= 4 and release_date[:4].isdigit():
        return int(release_date[:4])
    return None


def search_movie(title, year, api_key):
    payload = _tmdb_get("/search/movie", api_key, query=title, year=year or "")
    return [
        Candidate(
            tmdb_id=hit["id"],
            title=hit.get("title", ""),
            original_title=hit.get("original_title", ""),
            year=_release_year(hit.get("release_date")),
        )
        for hit in payload.get("results", [])
    ]


def film_from_payload(payload):
    """Builds FilmData from a /movie/{id}?append_to_response=credits
    payload. Pure function — the network-free part, tested separately."""
    genre_slugs = []
    for genre in payload.get("genres", []):
        slug = TMDB_GENRE_MAP.get(genre.get("id"))
        if slug and slug not in genre_slugs:
            genre_slugs.append(slug)
    genre_slugs = genre_slugs[:MAX_GENRES_PER_FILM]

    countries = payload.get("production_countries") or []
    poster_path = payload.get("poster_path")

    credits = []
    seen = set()
    cast = sorted(payload.get("credits", {}).get("cast", []), key=lambda c: c.get("order", 0))
    for member in cast[:CAST_LIMIT]:
        person = _person_from_tmdb(member)
        credits.append(
            CreditData(person, "act", character=member.get("character", "") or "",
                       billing=member.get("order"))
        )
        seen.add((person.tmdb_id, "act"))
    for member in payload.get("credits", {}).get("crew", []):
        role = CREW_JOBS.get(member.get("job", ""))
        if role is None or (member.get("id"), role) in seen:
            continue
        seen.add((member.get("id"), role))
        credits.append(CreditData(_person_from_tmdb(member), role))

    return FilmData(
        tmdb_id=payload["id"],
        title=payload.get("title", ""),
        original_title=payload.get("original_title", "") or "",
        year=_release_year(payload.get("release_date")),
        imdb_id=payload.get("imdb_id") or "",
        poster_url=f"{TMDB_IMAGES}/w342{poster_path}" if poster_path else "",
        runtime=payload.get("runtime") or None,
        country=countries[0].get("name", "") if countries else "",
        genre_slugs=genre_slugs,
        credits=credits,
    )


def _person_from_tmdb(member):
    profile_path = member.get("profile_path")
    return PersonData(
        name=member.get("name", ""),
        original_name=member.get("original_name", "") or "",
        tmdb_id=member.get("id"),
        photo_url=f"{TMDB_IMAGES}/w185{profile_path}" if profile_path else "",
    )


def fetch_movie(tmdb_id, api_key):
    payload = _tmdb_get(f"/movie/{tmdb_id}", api_key, append_to_response="credits")
    return film_from_payload(payload)


def _wikidata_query(imdb_id):
    unions = "\n    UNION ".join(
        f'{{ ?film wdt:{prop} ?person . BIND("{role}" AS ?role) }}'
        for prop, role in WIKIDATA_ROLES.items()
    )
    return f"""
SELECT ?role ?person ?personLabel WHERE {{
  ?film wdt:P345 "{imdb_id}" .
  {unions}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en" . }}
}}"""


def wikidata_credits(imdb_id):
    """Credits from Wikidata by IMDb id, grouped by role slug.

    For 1920s–1950s cinema TMDB routinely has no cinematographer or
    composer; one SPARQL query fills those in. The caller passes only the
    roles TMDB did not provide.
    """
    if not imdb_id:
        return {}
    # Be polite to the public endpoint: pause before the request, send an
    # identifying User-Agent.
    time.sleep(1)
    try:
        response = requests.get(
            WIKIDATA_SPARQL,
            params={"query": _wikidata_query(imdb_id), "format": "json"},
            headers={"User-Agent": USER_AGENT},
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise ResolverError(f"Wikidata request failed: {exc}") from exc
    return parse_wikidata_response(payload)


def parse_wikidata_response(payload):
    """Pure part of wikidata_credits, tested separately."""
    by_role = {}
    seen = set()
    for binding in payload.get("results", {}).get("bindings", []):
        role = binding.get("role", {}).get("value", "")
        uri = binding.get("person", {}).get("value", "")
        name = binding.get("personLabel", {}).get("value", "")
        qid = uri.rsplit("/", 1)[-1] if uri else ""
        if role not in WIKIDATA_ROLES.values() or not name or (qid, role) in seen:
            continue
        # A bare Q-id label means Wikidata has no readable name — skip.
        if name == qid:
            continue
        seen.add((qid, role))
        by_role.setdefault(role, []).append(PersonData(name=name, wikidata_id=qid))
    return by_role
