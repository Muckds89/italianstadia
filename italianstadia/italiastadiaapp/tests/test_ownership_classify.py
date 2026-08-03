"""Regression tests for classify_ownership (scripts/populate_data_from_transfermrkt).

Guards the class of bug where a public keyword substring-matched a non-public word
(notably " stad" matching the WORD "Stadium"/"Stadion"/"Stade"), tagging privately or
company-owned grounds as PUBLIC.
"""
import os
import sys

import pytest

SCRIPTS = os.path.join(os.path.dirname(__file__), "..", "..", "scripts")
sys.path.insert(0, os.path.abspath(SCRIPTS))

from populate_data_from_transfermrkt import classify_ownership  # noqa: E402


@pytest.mark.parametrize("owner_raw", [
    "An der Alten Försterei Stadionbetriebs AG",   # club-owned company
    "Kaiserlinde Stadiongesellschaft mbH & Co. KG",
    "Millennium Stadium plc ( Welsh Rugby Union )",
    "Brann Stadion AS",
    "Seinäjoki Stadion Oy",
])
def test_stadium_word_not_public(owner_raw):
    """The word 'Stadium/Stadion' must not by itself make a ground PUBLIC."""
    assert classify_ownership(owner_raw) != "PUBLIC"


@pytest.mark.parametrize("owner_raw,expected", [
    ("Stad Gent", "PUBLIC"),                 # legitimate Dutch/Flemish "stad " prefix
    ("Gemeente Amsterdam", "PUBLIC"),
    ("Comune di Milano", "PUBLIC"),
    ("Waltham Forest Council", "PUBLIC"),
    ("", "UNKNOWN"),
    ("FC Bayern München AG", "PRIVATE"),
])
def test_known_classifications(owner_raw, expected):
    assert classify_ownership(owner_raw) == expected


# ---------------------------------------------------------------------------
# Wikidata owner-entity TYPE classification.
#
# Wikidata returns owners as bare entity labels — "Kortrijk", "Lommel",
# "Barcelona" — which carry no wording for the public-keyword list to match, so
# classify_ownership defaulted every one of them to PRIVATE. That published
# municipally owned grounds as privately owned. The owner entity's P31
# ("instance of") disambiguates what the name alone cannot: "Barcelona" the
# football club vs "Kortrijk" the municipality.
# ---------------------------------------------------------------------------

def _kind(types):
    import importlib.util
    import os
    from django.conf import settings
    spec = importlib.util.spec_from_file_location(
        "_tm_scraper_wd",
        os.path.join(settings.BASE_DIR, "scripts", "populate_data_from_transfermrkt.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod._wd_kind_from_types(types)


@pytest.mark.parametrize("types", [
    ["Belgian municipality with the title of city"],
    ["municipality of Belgium"],
    ["municipality of the Netherlands"],
    ["sovereign state", "unitary state"],
    ["administrative centre", "big city"],
    ["big city", "college town"],
])
def test_administrative_owner_is_public(types):
    assert _kind(types) == "PUBLIC"


@pytest.mark.parametrize("types", [
    ["association football club"],
    ["multisports club", "not-for-profit organization"],
    ["business", "enterprise"],
])
def test_club_or_company_owner_is_private(types):
    assert _kind(types) == "PRIVATE"


def test_unrecognised_type_returns_none_rather_than_guessing():
    """No verdict is better than a wrong one — the caller keeps the keyword result."""
    assert _kind(["something we have never seen"]) is None
    assert _kind([]) is None
