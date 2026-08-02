"""Guard the deploy fixture against values Postgres will reject.

Local dev runs on SQLite, which does NOT enforce ``varchar(n)`` lengths, so an
over-long value (e.g. Country.code='GB-SCT' in a 2-char column) saves happily and
only explodes on Render during ``loaddata``:

    django.db.utils.DataError: value too long for type character varying(2)

The fixture is what actually deploys, so validate it directly: every CharField
value in initial_data.json must fit its model's max_length.
"""
import json
import os

import pytest
from django.apps import apps
from django.conf import settings
from django.db import models

FIXTURE = os.path.join(
    settings.BASE_DIR, "italiastadiaapp", "fixtures", "initial_data.json")


def _records():
    with open(FIXTURE, encoding="utf-8") as f:
        return json.load(f)


@pytest.mark.skipif(not os.path.exists(FIXTURE), reason="fixture not present")
def test_fixture_char_values_fit_their_columns():
    """No CharField value may exceed its max_length — Postgres enforces this
    even though SQLite silently accepts it."""
    violations = []
    for rec in _records():
        model = apps.get_model(*rec["model"].split("."))
        for fname, value in rec["fields"].items():
            try:
                field = model._meta.get_field(fname)
            except Exception:
                continue
            if not isinstance(field, models.CharField) or field.max_length is None:
                continue
            if isinstance(value, str) and len(value) > field.max_length:
                violations.append(
                    f"{rec['model']}(pk={rec.get('pk')}).{fname} = {value!r} "
                    f"({len(value)} chars > max_length={field.max_length})"
                )
    assert not violations, (
        "Fixture values too long for their columns — these WILL fail "
        "`loaddata` on Postgres:\n  " + "\n  ".join(violations)
    )


@pytest.mark.skipif(not os.path.exists(FIXTURE), reason="fixture not present")
def test_country_codes_are_two_chars():
    """Country.code is the field this has broken on twice (GB-WLS/GB-NIR, then
    GB-SCT). Home nations use the project's 2-char placeholders — England GB,
    Scotland SC, Wales WL, Northern Ireland NI — mapped to real flags by
    _FLAG_CODE_OVERRIDES."""
    bad = [
        (r["fields"].get("name"), r["fields"].get("code"))
        for r in _records()
        if r["model"] == "italiastadiaapp.country"
        and len(r["fields"].get("code") or "") > 2
    ]
    assert not bad, f"Country codes longer than 2 chars: {bad}"


def test_scraper_configs_use_two_char_country_codes():
    """Catch it at the source too: a bad country_code in a urls_*.json config is
    what put GB-SCT in the database in the first place."""
    import glob
    bad = []
    for path in glob.glob(os.path.join(settings.BASE_DIR, "scripts", "data", "urls_*.json")):
        with open(path, encoding="utf-8") as f:
            code = (json.load(f).get("league", {}) or {}).get("country_code") or ""
        if len(code) > 2:
            bad.append(f"{os.path.basename(path)}: {code!r}")
    assert not bad, f"Scraper configs with over-long country_code: {bad}"
