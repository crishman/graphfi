from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from films import resolver
from films.models import Credit, Film, Genre, Person


class Command(BaseCommand):
    help = (
        "Fill film metadata from TMDB, then top up missing roles from "
        "Wikidata. Never overwrites filled fields — only fills empty ones."
    )

    def add_arguments(self, parser):
        parser.add_argument("--auto", action="store_true",
                            help="No questions: take the first candidate whose year matches.")
        parser.add_argument("--id", type=int, help="Resolve a single film by primary key.")
        parser.add_argument("--force", action="store_true",
                            help="Also process films already linked to TMDB.")

    def handle(self, *args, **options):
        api_key = settings.TMDB_API_KEY
        if not api_key:
            raise CommandError("TMDB_API_KEY is empty — set it in the environment.")

        films = Film.objects.all().order_by("year", "title")
        if options["id"]:
            films = films.filter(pk=options["id"])
            if not films.exists():
                raise CommandError(f"No film with id={options['id']}.")
        elif not options["force"]:
            films = films.filter(tmdb_id__isnull=True)

        done = skipped = 0
        for film in films:
            try:
                if self.resolve_film(film, api_key, options["auto"]):
                    done += 1
                else:
                    skipped += 1
            except resolver.ResolverError as exc:
                self.stderr.write(self.style.ERROR(f"{film}: {exc}"))
                skipped += 1
        self.stdout.write(self.style.SUCCESS(f"Resolved {done}, skipped {skipped}."))

    # -- one film ---------------------------------------------------------

    def resolve_film(self, film, api_key, auto):
        candidates = resolver.search_movie(film.title, film.year, api_key)
        if not candidates and film.original_title:
            candidates = resolver.search_movie(film.original_title, film.year, api_key)
        if not candidates:
            self.stdout.write(self.style.WARNING(f"{film}: no TMDB candidates."))
            return False

        candidate = self.pick(film, candidates, auto)
        if candidate is None:
            self.stdout.write(f"{film}: skipped.")
            return False

        clash = Film.objects.filter(tmdb_id=candidate.tmdb_id).exclude(pk=film.pk).first()
        if clash:
            self.stdout.write(self.style.WARNING(
                f"{film}: TMDB id {candidate.tmdb_id} already belongs to {clash} — skipped."
            ))
            return False

        data = resolver.fetch_movie(candidate.tmdb_id, api_key)
        self.apply_film(film, data)
        self.apply_wikidata(film)
        self.stdout.write(f"{film}: ok (tmdb {film.tmdb_id}).")
        return True

    def pick(self, film, candidates, auto):
        if auto:
            for candidate in candidates:
                if candidate.year == film.year:
                    return candidate
            self.stdout.write(self.style.WARNING(
                f"{film}: no candidate matches the year — skipped in --auto mode."
            ))
            return None
        self.stdout.write(self.style.MIGRATE_HEADING(f"\n{film}"))
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

    def apply_film(self, film, data):
        """Fill empty fields only; the resolver never wins over the owner's
        own edits."""
        film.tmdb_id = data.tmdb_id
        for attr in ("original_title", "imdb_id", "poster_url", "country"):
            if not getattr(film, attr) and getattr(data, attr):
                setattr(film, attr, getattr(data, attr))
        if film.runtime is None and data.runtime:
            film.runtime = data.runtime
        film.save()

        if not film.genres.exists() and data.genre_slugs:
            film.genres.set(Genre.objects.filter(slug__in=data.genre_slugs))

        for credit in data.credits:
            person = self.person_for(credit.person)
            Credit.objects.get_or_create(
                film=film, person=person, role=credit.role,
                defaults={"character": credit.character, "billing": credit.billing},
            )

    def apply_wikidata(self, film):
        """Top up only the roles TMDB left empty. A Wikidata failure must
        not take the whole resolve run down."""
        if not film.imdb_id:
            return
        present = set(film.credits.values_list("role", flat=True))
        missing = [r for r in resolver.WIKIDATA_ROLES.values() if r not in present]
        if not missing:
            return
        try:
            by_role = resolver.wikidata_credits(film.imdb_id)
        except resolver.ResolverError as exc:
            self.stderr.write(self.style.WARNING(f"{film}: {exc}"))
            return
        for role in missing:
            for person_data in by_role.get(role, []):
                person = self.person_for(person_data)
                Credit.objects.get_or_create(film=film, person=person, role=role)

    def person_for(self, data):
        """Match an existing person before creating one, so repeated
        `resolve --force` runs never mint duplicates."""
        person = None
        if data.tmdb_id:
            person = Person.objects.filter(tmdb_id=data.tmdb_id).first()
        if person is None and data.wikidata_id:
            person = Person.objects.filter(wikidata_id=data.wikidata_id).first()
        if person is None:
            person = Person.objects.filter(name__iexact=data.name).first()
        if person is None:
            return Person.objects.create(
                name=data.name,
                original_name=data.original_name,
                tmdb_id=data.tmdb_id,
                wikidata_id=data.wikidata_id,
                photo_url=data.photo_url,
            )
        if person.tmdb_id is None and data.tmdb_id:
            if not Person.objects.filter(tmdb_id=data.tmdb_id).exclude(pk=person.pk).exists():
                person.tmdb_id = data.tmdb_id
        for attr in ("original_name", "wikidata_id", "photo_url"):
            if not getattr(person, attr) and getattr(data, attr):
                setattr(person, attr, getattr(data, attr))
        person.save()
        return person
