#!/usr/bin/env bash
#
# Run graphfi on this machine the way it should run outside development:
# DEBUG off, a generated secret key, WhiteNoise serving the collected static
# files, gunicorn instead of the development server.
#
#   deploy/run-local.sh                  # http://127.0.0.1:8000/
#   PORT=9000 deploy/run-local.sh
#   HOST=0.0.0.0 deploy/run-local.sh     # reachable from the LAN — see README
#
# Stage 2 of graphfi-plan.md (publishing on a domain) should change this file
# and DJANGO_ALLOWED_HOSTS, and nothing in films/.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

PY=.venv/bin/python
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"

[ -x "$PY" ] || { echo "no virtualenv at .venv — see README, Running" >&2; exit 1; }

if ! "$PY" -c "import gunicorn, whitenoise" 2>/dev/null; then
    echo "deploy dependencies missing — run:" >&2
    echo "    .venv/bin/pip install -r requirements-deploy.txt" >&2
    exit 1
fi

# A real SECRET_KEY, generated once, kept out of git, never printed. Sessions
# and the admin login survive restarts because the file persists; delete it and
# everyone is logged out.
KEY_FILE=.secret_key
if [ ! -s "$KEY_FILE" ]; then
    ( umask 077
      "$PY" -c "from django.core.management.utils import get_random_secret_key as g; print(g())" > "$KEY_FILE" )
    mode="$(stat -c %A "$KEY_FILE" 2>/dev/null || echo unknown)"
    case "$mode" in
        -rw-------|-r--------) echo "generated $KEY_FILE, owner-only" ;;
        *)  echo "generated $KEY_FILE — mode is $mode, not owner-only: this"
            echo "  filesystem does not carry POSIX permissions (a /mnt drive under WSL"
            echo "  is 9p and ignores umask). Anyone with access to the drive can read"
            echo "  the key; on a real deployment put the checkout on a Linux filesystem." ;;
    esac
fi
DJANGO_SECRET_KEY="$(cat "$KEY_FILE")"
export DJANGO_SECRET_KEY
export DJANGO_DEBUG=0
export DJANGO_ALLOWED_HOSTS="${DJANGO_ALLOWED_HOSTS:-127.0.0.1,localhost}"

# Migrations are the only step here that can lose data, so the database is
# copied first whenever any are unapplied. `migrate --check` exits non-zero
# exactly in that case.
if ! "$PY" manage.py migrate --check >/dev/null 2>&1; then
    stamp="$(date +%Y%m%d_%H%M%S)"
    mkdir -p backups
    cp db.sqlite3 "backups/db.sqlite3.${stamp}.before-migrate"
    echo "unapplied migrations — database copied to backups/db.sqlite3.${stamp}.before-migrate"
fi
"$PY" manage.py migrate --noinput
"$PY" manage.py collectstatic --noinput --verbosity 0

echo "graphfi on http://${HOST}:${PORT}/   (ctrl-c to stop)"

# One worker on purpose: SQLite locks the whole file for a write, and threads
# inside one process share a connection pool instead of fighting over it. One
# reader is all this journal has.
exec .venv/bin/gunicorn graphfi.wsgi:application \
    --bind "${HOST}:${PORT}" \
    --workers 1 --threads 4 \
    --timeout 60 \
    --access-logfile - --error-logfile -
