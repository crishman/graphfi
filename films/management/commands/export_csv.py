import csv

from django.core.management.base import BaseCommand

from films.models import Film

COLUMNS = [
    "id", "title", "original_title", "year", "rating", "watched_at",
    "genres", "country", "runtime", "tmdb_id", "imdb_id", "wikidata_id",
    "poster_url", "note",
]


class Command(BaseCommand):
    help = "Export all films to CSV. Credits do not travel through CSV — that is resolve's job."

    def add_arguments(self, parser):
        parser.add_argument("--out", required=True, help="Output file path.")

    def handle(self, *args, **options):
        films = Film.objects.all().prefetch_related("genres").order_by("year", "title")
        with open(options["out"], "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(COLUMNS)
            for film in films:
                writer.writerow([
                    film.pk,
                    film.title,
                    film.original_title,
                    film.year,
                    film.rating if film.rating is not None else "",
                    film.watched_at.isoformat() if film.watched_at else "",
                    ",".join(g.slug for g in film.genres.all()),
                    film.country,
                    film.runtime if film.runtime is not None else "",
                    film.tmdb_id if film.tmdb_id is not None else "",
                    film.imdb_id,
                    film.wikidata_id,
                    film.poster_url,
                    film.note,
                ])
        self.stdout.write(self.style.SUCCESS(f"Exported {films.count()} films to {options['out']}."))
