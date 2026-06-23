#!/usr/bin/env bash
set -o errexit

pip install -r requirements.txt
python manage.py migrate
# Sync the full dataset to prod. The app data lives in local SQLite and reaches prod ONLY
# via this fixture (scraped leagues are not re-scraped on the server). The fixture is
# regenerated from the local DB with `dumpdata` after data changes — see CLAUDE.md.
# loaddata upserts by PK, so re-running on each deploy is safe/idempotent.
python manage.py loaddata initial_data
# Refresh the clubs-per-city insight artifact from the freshly loaded data
# (cheap, query-only). Must run AFTER loaddata and BEFORE collectstatic.
python manage.py generate_city_clubs
python manage.py collectstatic --noinput