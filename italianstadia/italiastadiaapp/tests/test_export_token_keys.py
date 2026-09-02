"""
The paid download must render the SAME map the customer previewed.

The preview is rendered straight from the query string. The paid file is rebuilt
later, from the parameters stored on the ExportToken at checkout — and those are
filtered through a whitelist. Anything missing from that whitelist is dropped in
silence: no error, no warning, just a different map in the file someone paid for.

That happened. `uefa` was added for the continental competition maps and never added
to the whitelist, so buying a Conference League map returned every ground in Europe,
roughly a thousand clubs instead of thirty-two. Six more were missing alongside it.

A hand-kept list that has to track another function will drift again, so this test
reads both and compares them.
"""
import inspect
import re

from django.test import SimpleTestCase

from italiastadiaapp.views import _EXPORT_TOKEN_KEYS, _parse_export_params

_GET_KEY = re.compile(r"""request\.GET\.get\(\s*["']([a-z_]+)["']""")


def _params_the_renderer_reads():
    return set(_GET_KEY.findall(inspect.getsource(_parse_export_params)))


class ExportTokenKeyTests(SimpleTestCase):

    def test_every_renderer_parameter_survives_payment(self):
        dropped = _params_the_renderer_reads() - _EXPORT_TOKEN_KEYS
        self.assertEqual(
            dropped, set(),
            "These parameters are read when rendering but are NOT stored on the "
            "ExportToken, so the paid download silently ignores them and returns a "
            f"different map from the preview: {sorted(dropped)}. Add them to "
            "_EXPORT_TOKEN_KEYS in views.py.")

    def test_the_filters_that_change_which_grounds_appear_are_all_there(self):
        """Spelled out, because dropping one of these is the damaging case: the
        customer gets a map of the wrong grounds, not merely the wrong styling."""
        for key in ("country", "league", "uefa", "tournament", "ownership",
                    "surface", "stadium_type", "national", "national_only", "layer"):
            self.assertIn(key, _EXPORT_TOKEN_KEYS, f"{key} would be lost on payment")

    def test_the_regex_actually_matches_something(self):
        """Guards the test itself: if _parse_export_params is ever refactored away
        from request.GET.get, the scan silently returns nothing and this file would
        pass while checking nothing at all."""
        self.assertGreater(len(_params_the_renderer_reads()), 20)
