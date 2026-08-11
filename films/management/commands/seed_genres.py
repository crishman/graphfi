from django.core.management.base import BaseCommand

from films.genres import GENRES
from films.models import Genre


class Command(BaseCommand):
    help = "Load the closed genre vocabulary from films/genres.py."

    def handle(self, *args, **options):
        created = updated = 0
        for order, (slug, label) in enumerate(GENRES):
            _, was_created = Genre.objects.update_or_create(
                slug=slug, defaults={"label": label, "order": order}
            )
            if was_created:
                created += 1
            else:
                updated += 1
        stale = Genre.objects.exclude(slug__in=[slug for slug, _ in GENRES])
        for genre in stale:
            self.stdout.write(
                self.style.WARNING(
                    f"'{genre.slug}' is not in the vocabulary; left in place "
                    f"({genre.films.count()} films). Remove it by hand if it is dead."
                )
            )
        self.stdout.write(self.style.SUCCESS(f"Genres: {created} created, {updated} updated."))
