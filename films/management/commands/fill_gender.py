from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from films import resolver
from films.models import Credit, Film, Person


class Command(BaseCommand):
    help = (
        "Fill in people's gender from TMDB for films already linked: one "
        "request per film, by its stored TMDB id. Touches nothing but empty "
        "gender fields — no search, no Wikidata, no new credits."
    )

    def handle(self, *args, **options):
        api_key = settings.TMDB_API_KEY
        if not api_key:
            raise CommandError("TMDB_API_KEY is empty — set it in the environment.")

        films = (Film.objects.filter(tmdb_id__isnull=False, credits__person__gender__isnull=True)
                 .distinct().order_by("year", "title"))
        filled = failed = 0
        for film in films:
            try:
                data = resolver.fetch_movie(film.tmdb_id, api_key)
            except resolver.ResolverError as exc:
                self.stderr.write(self.style.ERROR(f"{film}: {exc}"))
                failed += 1
                continue
            for credit in data.credits:
                person = credit.person
                if person.tmdb_id is None or person.gender is None:
                    continue
                filled += Person.objects.filter(
                    tmdb_id=person.tmdb_id, gender__isnull=True
                ).update(gender=person.gender)

        missing = (Person.objects.filter(gender__isnull=True, credits__role=Credit.Role.ACTOR)
                   .distinct().count())
        self.stdout.write(self.style.SUCCESS(
            f"Filled gender for {filled} people; {missing} actors still have none "
            f"on record{f', {failed} films failed' if failed else ''}."
        ))
