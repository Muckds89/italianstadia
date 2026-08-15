"""
Crest selection.

Two live maps shipped with the wrong badge and each failure had its own cause:

  * Real Madrid rendered a PHOTOGRAPH of Alfredo Di Stefano standing in a goal,
    because the club has no Wikidata P154 and the article-image fallback matched
    the club name in "Di stefano real madrid cf (cropped).png".
  * Athletic Club rendered its 1901 crest. MediaWiki returns an article's images
    in ALPHABETICAL order and the picker took the first keyword match, so
    "Athletic Club crest 1901.png" beat "Club Athletic Bilbao logo.svg" sitting
    six entries later in the same list.

The second is the dangerous one: it is a systematic bias toward the OLDEST badge
that hits precisely the clubs big enough to document their crest history. It put
a 1902 badge on MSV Duisburg and a 1933 one on Anderlecht -- 13 clubs in all.
"""
from django.test import SimpleTestCase

from italiastadiaapp.management.commands.refresh_dead_crests import (
    Command, is_historic)


class IsHistoricTests(SimpleTestCase):
    """A filename that dates itself describes a badge the club has retired."""

    def test_closed_date_range_is_retired(self):
        for fname in ("Logo Anderlecht 1933–1959.svg",
                      "LutonTownFCBadge1973-1987.png",
                      "Reading FC crest (1987-96).svg",
                      "Logo MSV Duisburg 1902-1905.gif",
                      "1947-1962 FK Sarajevo crest.png",
                      "(1945-1947) KS Ruch Chorzów Batory.svg",
                      "Associazione Calcio Verona logo (1965-1984).png",
                      "FK Suduva logo 1968-2025.svg"):
            self.assertTrue(is_historic(fname), fname)

    def test_explicit_former_wording_is_retired(self):
        for fname in ("Former logo of Kasımpaşa SK (1996-2012).png",
                      "Stade Brestois Logo avant 1985.svg",
                      "VfL Osnabrück (1930er Jahre Kurmark).svg"):
            self.assertTrue(is_historic(fname), fname)

    def test_centenary_mark_is_not_the_crest(self):
        # a 100-year commemorative logo is worn for one season, if at all
        for fname in ("Feyenoord logo 100 years.svg",
                      "Logo Lech Poznań 100 1922-2022.jpg"):
            self.assertTrue(is_historic(fname), fname)

    def test_open_ended_range_is_the_current_badge(self):
        # "2015-heden" is Dutch for "2015-present"; an unclosed span is in use
        for fname in ("Go Ahead Eagles logo 2015-heden.png",
                      "VfL Osnabrueck Logo 2021–.svg",
                      "1. FC Koeln Logo 2014–.svg",
                      "Logo of Spezia Calcio (2025-).svg"):
            self.assertFalse(is_historic(fname), fname)

    def test_readopted_badge_survives_its_own_closed_range(self):
        # Ajax brought a 1928 badge back in 2025 and the file records both spans
        self.assertFalse(is_historic("Logo AFC Ajax (1928-1991, 2025-).png"))

    def test_founding_year_in_the_club_name_is_not_a_date_range(self):
        for fname in ("Bologna F.C. 1909 logo.svg", "VfB Stuttgart 1893 Logo.svg",
                      "Ascoli Calcio 1898 logo.svg", "Cagliari Calcio 1920.svg",
                      "1. FC Heidenheim 1846.svg"):
            self.assertFalse(is_historic(fname), fname)


class PickArticleImageTests(SimpleTestCase):
    """The fallback scan must not be decided by alphabetical position."""

    def test_current_logo_beats_alphabetically_earlier_historic_crest(self):
        # the exact list that mis-picked Athletic Club, in MediaWiki's order
        images = ["File:Athletic Club crest 1901.png",
                  "File:Athletic Club crest 1903.png",
                  "File:Athletic Club crest 1910.png",
                  "File:Club Athletic Bilbao logo.svg"]
        self.assertEqual(Command._pick_article_image(images, "Athletic Bilbao"),
                         "File:Club Athletic Bilbao logo.svg")

    def test_dated_badge_loses_to_undated_one(self):
        images = ["File:Escudo Real Madrid 1908.png", "File:Real Madrid CF.svg"]
        self.assertEqual(Command._pick_article_image(images, "Real Madrid CF"),
                         "File:Real Madrid CF.svg")

    def test_photograph_named_after_the_club_is_never_picked(self):
        # a png whose name merely contains the club is not a crest
        images = ["File:Di stefano real madrid cf (cropped).png"]
        self.assertIsNone(Command._pick_article_image(images, "Real Madrid CF"))

    def test_returns_none_rather_than_guessing(self):
        images = ["File:Commons-logo.svg", "File:Some Stadium 2019.jpg"]
        self.assertIsNone(Command._pick_article_image(images, "Real Madrid CF"))

    def test_svg_preferred_over_png_when_both_look_like_crests(self):
        images = ["File:Reading FC crest.png", "File:Reading FC crest.svg"]
        self.assertEqual(Command._pick_article_image(images, "Reading FC"),
                         "File:Reading FC crest.svg")


class InfoboxRegexTests(SimpleTestCase):
    """The infobox param is the authoritative source and is tried first.

    Wikidata P154 is absent for Real Madrid and Athletic Club alike, which is
    exactly how both reached the buggy fallback.
    """

    def _pick(self, wikitext):
        m = Command._INFOBOX_IMG.search(wikitext)
        return m.group(1).strip() if m else None

    def test_reads_the_image_parameter(self):
        self.assertEqual(
            self._pick("{{Infobox football club\n| clubname = Real Madrid\n"
                       "| image = Real Madrid CF.svg\n| fullname = ...\n"),
            "Real Madrid CF.svg")

    def test_strips_a_file_prefix_and_link_brackets(self):
        self.assertEqual(
            self._pick("| logo = [[File:Club Athletic Bilbao logo.svg\n"),
            "Club Athletic Bilbao logo.svg")

    def test_ignores_an_empty_parameter(self):
        self.assertIsNone(self._pick("| image = \n| fullname = X\n"))
