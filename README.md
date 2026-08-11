# graphfi

A personal film-watching journal with analytics. Django + SQLite, charts are
SVG assembled in Python. No JavaScript at all.

The owner watches cinema as a systematic survey by year, starting from 1920.
The core value is **seeing the picture fill in as you advance through the
years** — not maintaining a catalogue. Everything else serves that.

## Running

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python manage.py migrate
python manage.py seed_genres          # load the closed genre vocabulary
python manage.py createsuperuser
python manage.py runserver
```

- `http://127.0.0.1:8000/` — profile with the charts
- `http://127.0.0.1:8000/add/` — batch add
- `http://127.0.0.1:8000/admin/` — edit everything

## How to use it

**1. Dump in a list.** On `/add/` paste lines like
`Title | year | rating | date | genres`. Rating, date and genres are
optional — you can load a watchlist first and rate later in the admin
(ratings and watch dates are editable right in the list view, no need to
open film pages).

**2. Pull in metadata.**

```bash
export TMDB_API_KEY=[API_KEY]
python manage.py resolve            # asks which candidate is right, film by film
python manage.py resolve --auto     # no questions, first candidate matching the year
python manage.py resolve --id 42    # a single film
python manage.py resolve --force    # including films already linked
```

Posters and photos are never downloaded — the database stores only links to
the TMDB CDN. That is deliberate: other people's images are embedded, not
reproduced.

For 1920s–1950s cinema TMDB often has no cinematographers or composers, so
after TMDB the resolver tops up the missing roles from Wikidata by IMDb id.
Wikidata data is CC0; TMDB requires attribution — the footer already carries
"This product uses the TMDB API but is not endorsed or certified by TMDB".

The resolver never overwrites fields you filled by hand — it only fills
empty ones.

**3. Mass edits.**

```bash
python manage.py export_csv --out films.csv
# edit in whatever you like
python manage.py import_csv films.csv --dry-run
python manage.py import_csv films.csv
```

Import matching order: `id`, then `tmdb_id`, then the title + year pair.
Credits do not travel through CSV — that is `resolve`'s job. `--dry-run`
runs everything in a transaction and rolls it back.

## What is on the dashboard

- **The strip** — one frame per release year, from the first rated year to
  the last. Frame brightness is the year's average rating; a dark frame is a
  year not touched yet. Clicking a frame opens that year's films. This is
  the picture of progress.
- **Ratings** — a dot per film by release year with a yearly-average line;
  switches to a watch-date axis. Clicking a dot opens the film.
- **Genres** — average per genre, plus a genre × decade matrix.
- **People** — actors, directors, cinematographers, composers, writers: film
  count and average rating each. People with fewer than three films are
  collapsed separately: an average over one film is noise, not signal.

## Settings

`graphfi/settings.py`:
- `MIN_FILMS_FOR_RANKING` — threshold for the main people ranking (default 3)
- `TMDB_API_KEY` — read from the environment

`films/genres.py` — the closed genre vocabulary and the per-film tag limit.
After editing the vocabulary run `python manage.py seed_genres`.

## Before publishing anywhere

`DEBUG=False`, `SECRET_KEY` from the environment (`DJANGO_SECRET_KEY`),
`ALLOWED_HOSTS` (`DJANGO_ALLOWED_HOSTS`), static files via whitenoise or
nginx. SQLite will hold up fine there for a single user.

## Structure

```
films/
  models.py      Film, Person, Genre, Credit
  genres.py      closed genre vocabulary + TMDB genre map
  stats.py       aggregates (pure functions, render nothing)
  charts.py      SVG generation (takes stats output, never hits the DB)
  bulk.py        batch-input parsing
  resolver.py    TMDB + Wikidata (does not import Django)
  views.py       glue: stats + charts + templates
  admin.py       editing workbench
  management/commands/   seed_genres, resolve, export_csv, import_csv
```
