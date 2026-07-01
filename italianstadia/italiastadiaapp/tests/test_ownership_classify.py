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
