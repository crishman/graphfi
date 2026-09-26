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

## Running it properly on this machine

The block above is Django's development server. To run graphfi the way it
should run outside development — `DEBUG` off, a generated `SECRET_KEY`, static
files actually served, gunicorn instead of `runserver`:

```bash
.venv/bin/pip install -r requirements-deploy.txt   # gunicorn + whitenoise
deploy/run-local.sh                                # http://127.0.0.1:8000/
```

The script generates `.secret_key` on first run (gitignored, never printed),
copies the database into `backups/` if any migration is unapplied, runs
`collectstatic`, then starts gunicorn on 127.0.0.1 with one worker — SQLite
locks the whole file for a write, and one reader is all this journal has.

`PORT=9000` and `HOST=0.0.0.0` override the defaults; anything but 127.0.0.1
also needs the host name in `DJANGO_ALLOWED_HOSTS`. Note before opening it to a
network: `/add/` and the rating widget have no login, so everyone who can reach
the page can add films and overwrite ratings.

`deploy/graphfi.service` is a systemd user unit for keeping it running in the
background; its header carries the three commands to install it.

In this configuration `manage.py check --deploy` reports four warnings, all of
them about HTTPS and secure cookies — a plain-HTTP localhost run cannot satisfy
them, and they become real on the day this moves to a domain.

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
python manage.py resolve --force    # also refresh films already linked
python manage.py fill_gender        # once, for people resolved before gender was kept
```

A film already linked is refreshed from its stored TMDB id and never searched
again, so `--force` cannot move it to a different TMDB entry. To fix a wrong
match, clear the film's TMDB id in the admin and resolve it again.

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
  Actors, directors and cinematographers are sliced by film form —
  features, shorts (40 minutes or under), animation — so a run of
  two-reelers or cartoons does not outvote features. The form is derived
  from the genre and runtime every time; nothing extra is stored.
  The feature cast alone is split again into actors and actresses, by the
  gender TMDB records; shorts, animation and the other roles keep one table.
  Feature actors with no gender on record are listed under both tables
  rather than dropped, and their gender can be set in the admin.

## Tests

```bash
python manage.py test tests.unit
```

Unit tests cover the SVG chart functions, aggregates, batch-input parsing,
the TMDB/Wikidata payload parsing (fixtures, no network), the resolve
command's fill-only-empty and no-duplicates guarantees, views, and the CSV
commands.

## Settings

`graphfi/settings.py`:
- `MIN_FILMS_FOR_RANKING` — threshold for the main people ranking (default 3)
- `SHORT_FILM_MAX_MINUTES` — runtime at or under which a film is a short (default 40)
- `TMDB_API_KEY` — read from the environment

`films/genres.py` — the closed genre vocabulary and the per-film tag limit.
After editing the vocabulary run `python manage.py seed_genres`.

## Before publishing anywhere

`deploy/run-local.sh` already sets `DEBUG=False`, a real `SECRET_KEY`
(`DJANGO_SECRET_KEY`), `ALLOWED_HOSTS` (`DJANGO_ALLOWED_HOSTS`) and whitenoise
for static files, so a domain needs three things on top of it: TLS in front
(nginx or the platform), `SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE`,
`CSRF_COOKIE_SECURE` and `SECURE_HSTS_SECONDS` switched on once HTTPS holds,
and a login on `/add/` and `/film/<id>/rate/`, which are open to whoever can
reach them. SQLite will hold up fine there for a single user, but it must sit
on a disk that survives a redeploy.

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
