"""
Pure-logic guards for the map renderer.

NOTE ON SCOPE. The DATA checks that belong with these live in
`manage.py check_map_integrity`, not here. pytest runs against an EMPTY test
database — this project has no fixture loading in conftest — so an assertion like
"no stadium is missing coordinates" passes trivially by iterating nothing. Three
such tests were written here first and passed while the live database had five
grounds with no coordinates and fourteen pairs of grounds sharing a name.

What CAN be tested here is behaviour that does not depend on stored rows.
"""
from django.test import SimpleTestCase

from italiastadiaapp.views import _badge_key


class BadgeKeyTests(SimpleTestCase):
    """Two DIFFERENT grounds can share a name, and keying on the name loses one.

    Vicenza and Juve Stabia both play at a "Romeo Menti". Keying the prefetched
    badge dict on the stadium name collapsed them, so one club wore the other's
    crest; keying the inset's label-skip set on the name suppressed Vicenza's
    label on the main map as well, and the Serie B export silently rendered 19 of
    its 20 clubs. Fourteen name pairs in the live data are affected, so this was
    never specific to Italy.
    """

    def test_separates_grounds_that_share_a_name(self):
        rows = [{"slug": "romeo-menti", "name": "Romeo Menti"},
                {"slug": "romeo-menti-2", "name": "Romeo Menti"}]
        self.assertEqual(len({_badge_key(r) for r in rows}), 2)

    def test_prefers_the_slug_over_the_name(self):
        self.assertEqual(
            _badge_key({"slug": "romeo-menti-2", "name": "Romeo Menti"}),
            "romeo-menti-2")

    def test_falls_back_to_the_name_when_there_is_no_slug(self):
        # tournament and development venues are synthetic rows carrying no slug
        self.assertEqual(_badge_key({"name": "Wembley Stadium"}), "Wembley Stadium")
        self.assertEqual(_badge_key({"slug": "", "name": "Wembley Stadium"}),
                         "Wembley Stadium")

    def test_never_returns_none(self):
        # a key of None would collapse every unkeyable row onto one badge
        self.assertEqual(_badge_key({}), "")
