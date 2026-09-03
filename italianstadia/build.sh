#!/usr/bin/env bash
set -o errexit

pip install -r requirements.txt
# Run the system checks EXPLICITLY. `migrate` sets requires_system_checks = [], so it
# runs none of them — the runtime-compatibility check in italiastadiaapp/checks.py was
# documented as gating the deploy and in fact never ran. `check` exits non-zero on an
# Error, and errexit turns that into a failed build, which is the point: better a
# refused deploy than a site whose admin 500s on every page.
python manage.py check
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
python manage.py setup_admin