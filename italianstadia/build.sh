#!/usr/bin/env bash
set -o errexit

pip install -r requirements.txt
python manage.py migrate
python manage.py flush --noinput
python manage.py loaddata initial_data.json
python manage.py generate_stadiums_json   # pre-build static map file before collectstatic
python manage.py collectstatic --noinput