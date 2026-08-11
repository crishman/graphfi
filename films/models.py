from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from .genres import MAX_GENRES_PER_FILM


class Genre(models.Model):
    slug = models.SlugField("slug", unique=True)
    label = models.CharField("label", max_length=100)
    order = models.PositiveSmallIntegerField("order", default=0)

    class Meta:
        ordering = ["order", "slug"]
        verbose_name = "genre"
        verbose_name_plural = "genres"

    def __str__(self):
        return self.label


class Person(models.Model):
    name = models.CharField("name", max_length=200)
    original_name = models.CharField("original name", max_length=200, blank=True)
    tmdb_id = models.IntegerField("TMDB id", null=True, blank=True, unique=True)
    wikidata_id = models.CharField("Wikidata id", max_length=32, blank=True)
    # A link to the TMDB CDN, never a downloaded file — licensing requirement.
    photo_url = models.URLField("photo URL", blank=True)
    birth_year = models.IntegerField("birth year", null=True, blank=True)
    death_year = models.IntegerField("death year", null=True, blank=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "person"
        verbose_name_plural = "people"

    def __str__(self):
        return self.name


class Film(models.Model):
    title = models.CharField("title", max_length=300)
    original_title = models.CharField("original title", max_length=300, blank=True)
    year = models.IntegerField("release year", db_index=True)
    tmdb_id = models.IntegerField("TMDB id", null=True, blank=True, unique=True)
    imdb_id = models.CharField("IMDb id", max_length=16, blank=True)
    wikidata_id = models.CharField("Wikidata id", max_length=32, blank=True)
    # A link to the TMDB CDN, never a downloaded file — licensing requirement.
    poster_url = models.URLField("poster URL", blank=True)
    runtime = models.PositiveIntegerField("runtime, min", null=True, blank=True)
    country = models.CharField("country", max_length=100, blank=True)
    rating = models.PositiveSmallIntegerField(
        "rating",
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(10)],
        help_text="Whole numbers 1–10, empty = not watched yet.",
    )
    watched_at = models.DateField("watched on", null=True, blank=True, db_index=True)
    note = models.TextField("note", blank=True)
    genres = models.ManyToManyField(Genre, verbose_name="genres", blank=True, related_name="films")

    class Meta:
        ordering = ["-year", "title"]
        constraints = [
            models.UniqueConstraint(fields=["title", "year"], name="unique_film_title_year"),
        ]
        verbose_name = "film"
        verbose_name_plural = "films"

    def __str__(self):
        return f"{self.title} ({self.year})"

    def clean(self):
        # The genre limit lives in form validation and here, not in the
        # schema: M2M rows are written after save, so the database cannot
        # enforce it.
        if self.pk and self.genres.count() > MAX_GENRES_PER_FILM:
            raise ValidationError(
                {"genres": f"No more than {MAX_GENRES_PER_FILM} genres per film."}
            )


class Credit(models.Model):
    class Role(models.TextChoices):
        DIRECTOR = "dir", "Director"
        ACTOR = "act", "Actor"
        COMPOSER = "comp", "Composer"
        CINEMATOGRAPHER = "dop", "Cinematographer"
        WRITER = "writ", "Writer"

    film = models.ForeignKey(
        Film, verbose_name="film", on_delete=models.CASCADE, related_name="credits"
    )
    person = models.ForeignKey(
        Person, verbose_name="person", on_delete=models.CASCADE, related_name="credits"
    )
    role = models.CharField("role", max_length=4, choices=Role.choices)
    character = models.CharField("character", max_length=200, blank=True)
    billing = models.PositiveSmallIntegerField("billing order", null=True, blank=True)

    class Meta:
        ordering = ["billing", "id"]
        constraints = [
            models.UniqueConstraint(fields=["film", "person", "role"], name="unique_credit"),
        ]
        indexes = [
            models.Index(fields=["person", "role"]),
            models.Index(fields=["role"]),
        ]
        verbose_name = "credit"
        verbose_name_plural = "credits"

    def __str__(self):
        return f"{self.person} — {self.get_role_display()} — {self.film}"
