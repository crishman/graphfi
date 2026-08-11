from django import forms
from django.contrib import admin

from .genres import MAX_GENRES_PER_FILM
from .models import Credit, Film, Genre, Person


class CreditInline(admin.TabularInline):
    model = Credit
    extra = 0
    autocomplete_fields = ["person"]
    fields = ["person", "role", "character", "billing"]


class FilmAdminForm(forms.ModelForm):
    class Meta:
        model = Film
        fields = "__all__"

    def clean_genres(self):
        genres = self.cleaned_data.get("genres")
        if genres is not None and genres.count() > MAX_GENRES_PER_FILM:
            raise forms.ValidationError(
                f"No more than {MAX_GENRES_PER_FILM} genres per film."
            )
        return genres


@admin.register(Film)
class FilmAdmin(admin.ModelAdmin):
    form = FilmAdminForm
    inlines = [CreditInline]
    list_display = ["title", "year", "rating", "watched_at", "genre_list", "tmdb_id"]
    # Rating and watch date are editable right in the list: a batch of
    # ratings gets entered without opening a single film page.
    list_editable = ["rating", "watched_at"]
    list_filter = ["rating", "genres", "year"]
    search_fields = ["title", "original_title"]
    filter_horizontal = ["genres"]
    date_hierarchy = "watched_at"
    list_per_page = 100

    @admin.display(description="genres")
    def genre_list(self, obj):
        return ", ".join(g.label for g in obj.genres.all())

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("genres")


@admin.register(Person)
class PersonAdmin(admin.ModelAdmin):
    list_display = ["name", "original_name", "birth_year", "death_year", "tmdb_id"]
    search_fields = ["name", "original_name"]


@admin.register(Genre)
class GenreAdmin(admin.ModelAdmin):
    list_display = ["slug", "label", "order"]
    # The vocabulary is closed: rows come from seed_genres, labels are the
    # only thing safe to touch here.
    def has_add_permission(self, request):
        return False


@admin.register(Credit)
class CreditAdmin(admin.ModelAdmin):
    list_display = ["film", "person", "role", "character", "billing"]
    list_filter = ["role"]
    autocomplete_fields = ["film", "person"]
    search_fields = ["film__title", "person__name"]
