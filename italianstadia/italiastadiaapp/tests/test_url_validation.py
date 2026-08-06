"""validate_wiki_urls is the MANDATORY gate before any scrape, so a false BROKEN
is not a cosmetic bug: it either blocks a correct dataset or invites someone to
"fix" a URL that was right all along.

Wikipedia URLs are stored readable ("/wiki/Bandırmaspor") because that is what you
paste from the address bar. urlopen ASCII-encodes the request line, so every such
URL raised UnicodeEncodeError, which the script's broad `except Exception` reported
as a broken link — silently failing every Turkish, Polish and accented article in
the project.
"""
import sys
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

sys.path.insert(0, str(Path(settings.BASE_DIR) / "scripts"))

from validate_wiki_urls import to_ascii_url  # noqa: E402


class ToAsciiUrlTests(SimpleTestCase):
    def test_turkish_dotless_i_is_encoded(self):
        self.assertEqual(
            to_ascii_url("https://en.wikipedia.org/wiki/Bandırmaspor"),
            "https://en.wikipedia.org/wiki/Band%C4%B1rmaspor")

    def test_non_english_wiki_host_is_preserved(self):
        """A tr./ru. wikipedia_url is a supported, preferred fix when only the
        native-language article carries the data — see CLAUDE.md."""
        out = to_ascii_url("https://tr.wikipedia.org/wiki/Van_Atatürk_Stadyumu")
        self.assertEqual(out, "https://tr.wikipedia.org/wiki/Van_Atat%C3%BCrk_Stadyumu")
        self.assertTrue(out.startswith("https://tr.wikipedia.org/"))

    def test_result_is_ascii_encodable(self):
        """The actual failure mode: http.client encodes the request line as ASCII."""
        for url in ("https://en.wikipedia.org/wiki/Muğlaspor",
                    "https://tr.wikipedia.org/wiki/21_Kasım_Stadyumu",
                    "https://en.wikipedia.org/wiki/Çorum_F.K.",
                    "https://pl.wikipedia.org/wiki/Stadion_Miejski_w_Białymstoku"):
            to_ascii_url(url).encode("ascii")  # must not raise

    def test_already_encoded_url_is_not_double_encoded(self):
        """%C3%BC must not become %25C3%25BC — that would 404 a valid article."""
        encoded = "https://en.wikipedia.org/wiki/W%C3%BCrzburger_Kickers"
        self.assertEqual(to_ascii_url(encoded), encoded)

    def test_plain_ascii_url_is_untouched(self):
        url = "https://en.wikipedia.org/wiki/AFC_Ajax"
        self.assertEqual(to_ascii_url(url), url)

    def test_query_and_fragment_survive(self):
        url = "https://en.wikipedia.org/w/index.php?title=Foo&action=edit"
        self.assertEqual(to_ascii_url(url), url)
