from django.conf import settings
from django.core.management.base import CommandError
from django.db import transaction

from films import resolver
from films.management.commands import resolve
from films.models import Genre, Season, SeasonCredit, Series


def _failure(exc):
    """What went wrong, without the request URL: it carries the API key."""
    response = getattr(exc.__cause__, "response", None)
    status = getattr(response, "status_code", None)
    return f"TMDB request failed (HTTP {status})" if status else "TMDB request failed (network)"


class Command(resolve.Command):
    help = (
        "Add a TV series from TMDB, or refresh the linked ones: the series, "
        "its seasons (specials skipped) and each season's regular cast, "
        "directors and creators. Fills empty fields only; ratings, watch "
        "dates and notes are never touched."
    )

    def add_arguments(self, parser):
        parser.add_argument("title", nargs="?", help="Series title to search TMDB for.")
        parser.add_argument("--year", type=int, help="First-air year, narrows the search.")
        parser.add_argument("--tmdb", type=int, help="Link by TMDB id, no search.")
        parser.add_argument("--auto", action="store_true",
                            help="No questions: take the first candidate (matching --year if given).")
        parser.add_argument("--refresh", action="store_true",
                            help="Refresh every linked series from its stored TMDB id.")

    def handle(self, *args, **options):
        api_key = settings.TMDB_API_KEY
        if not api_key:
            raise CommandError("TMDB_API_KEY is empty — set it in the environment.")

        if options["refresh"]:
            ids = list(Series.objects.filter(tmdb_id__isnull=False)
                       .order_by("first_year", "title").values_list("tmdb_id", flat=True))
        elif options["tmdb"]:
            ids = [options["tmdb"]]
        elif options["title"]:
            try:
                candidates = resolver.search_tv(options["title"], options["year"], api_key)
            except resolver.ResolverError as exc:
                raise CommandError(_failure(exc))
            candidate = self.pick_series(options["title"], options["year"], candidates, options["auto"])
            ids = [candidate.tmdb_id] if candidate else []
        else:
            raise CommandError("Give a title, --tmdb ID or --refresh.")

        done = failed = 0
        for tmdb_id in ids:
            try:
                self.apply_series(tmdb_id, api_key)
                done += 1
            except resolver.ResolverError as exc:
                self.stderr.write(self.style.ERROR(f"TMDB tv {tmdb_id}: {_failure(exc)} — nothing saved."))
                failed += 1
        self.stdout.write(self.style.SUCCESS(f"Series resolved {done}, failed {failed}."))

    def pick_series(self, title, year, candidates, auto):
        if not candidates:
            self.stdout.write(self.style.WARNING(f"{title}: no TMDB candidates."))
            return None
        if auto:
            for candidate in candidates:
                if year is None or candidate.year == year:
                    return candidate
            self.stdout.write(self.style.WARNING(
                f"{title}: no candidate matches the year — skipped in --auto mode."
            ))
            return None
        self.stdout.write(self.style.MIGRATE_HEADING(f"\n{title}"))
        for i, c in enumerate(candidates[:10], start=1):
            original = f" / {c.original_title}" if c.original_title != c.title else ""
            self.stdout.write(f"  {i}. {c.title}{original} ({c.year or '—'})")
        choice = input("  pick [Enter=1, number, s=skip]: ").strip().lower()
        if choice in ("s", "n", "q"):
            return None
        if not choice:
            return candidates[0]
        if choice.isdigit() and 1 <= int(choice) <= min(len(candidates), 10):
            return candidates[int(choice) - 1]
        return None

    # -- writing ----------------------------------------------------------

    def apply_series(self, tmdb_id, api_key):
        """One series, all or nothing: a failure on the fifth season must
        not leave four seasons half-written."""
        data = resolver.fetch_series(tmdb_id, api_key)
        if data.first_year is None:
            self.stdout.write(self.style.WARNING(f"{data.title}: no first-air date on TMDB — skipped."))
            return
        season_credits = {
            info.number: resolver.fetch_season_credits(data.tmdb_id, info.number,
                                                       info.episode_count, api_key)
            for info in data.seasons
        }
        with transaction.atomic():
            series = self.series_for(data)
            credits = 0
            for info in data.seasons:
                season = self.season_for(series, info)
                for credit in season_credits[info.number] + [
                    resolver.CreditData(person, "crea") for person in data.creators
                ]:
                    _, created = SeasonCredit.objects.get_or_create(
                        season=season, person=self.person_for(credit.person), role=credit.role,
                        defaults={"character": credit.character, "episodes": credit.episodes,
                                  "billing": credit.billing},
                    )
                    credits += created
        self.stdout.write(f"{series}: {len(data.seasons)} seasons, {credits} new credits.")

    def series_for(self, data):
        series = (Series.objects.filter(tmdb_id=data.tmdb_id).first()
                  or Series.objects.filter(title=data.title, first_year=data.first_year,
                                           tmdb_id__isnull=True).first()
                  or Series(title=data.title, first_year=data.first_year))
        series.tmdb_id = data.tmdb_id
        for attr in ("original_title", "imdb_id", "wikidata_id", "tv_type", "poster_url", "country"):
            if not getattr(series, attr) and getattr(data, attr):
                setattr(series, attr, getattr(data, attr))
        # A running series keeps airing, so the last year may move forward.
        if data.last_year and (series.last_year is None or data.last_year > series.last_year):
            series.last_year = data.last_year
        series.save()
        if not series.genres.exists() and data.genre_slugs:
            series.genres.set(Genre.objects.filter(slug__in=data.genre_slugs))
        return series

    def season_for(self, series, info):
        season, created = Season.objects.get_or_create(
            series=series, number=info.number,
            defaults={"name": info.name, "year": info.year,
                      "episode_count": info.episode_count, "poster_url": info.poster_url},
        )
        if not created:
            for attr in ("name", "year", "poster_url"):
                if not getattr(season, attr) and getattr(info, attr):
                    setattr(season, attr, getattr(info, attr))
            # A season on air gains episodes.
            if info.episode_count and (season.episode_count or 0) < info.episode_count:
                season.episode_count = info.episode_count
            season.save()
        return season
