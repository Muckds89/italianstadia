"""
Ownership classification.

Every case here is a row that was actually wrong in the live database. A Lille
supporter reported the category error on a published map; the rest came out of the
whole-database audit that followed.
"""
from django.test import SimpleTestCase

from italiastadiaapp.ownership import classify_ownership as classify


class SubstringFalsePositiveTests(SimpleTestCase):
    """Keywords used to match as bare substrings, anywhere inside a word.

    " stad" is Dutch for "city". It matched the English word "Stadium" and the
    German "Stadion", so sixteen grounds whose OWNER was a private stadium company
    were published as municipally owned.
    """

    def test_stadium_in_a_company_name_is_not_the_dutch_word_for_city(self):
        self.assertEqual(classify("The Community Stadium Limited"), "PRIVATE")
        self.assertEqual(classify("Allianz Arena München Stadion GmbH"), "PRIVATE")
        self.assertEqual(classify("Brann Stadion AS"), "PRIVATE")
        self.assertEqual(classify("VfL Osnabrück Stadion GmbH & Co. KG"), "PRIVATE")

    def test_the_real_dutch_word_still_matches(self):
        # the fix must not cost us the keyword it was protecting
        self.assertEqual(classify("Stad Mechelen"), "PUBLIC")
        self.assertEqual(classify("Stockholms stad"), "PUBLIC")

    def test_land_does_not_match_a_town_ending_in_land(self):
        # German "Land " matched "Sunderland 100%", making the Stadium of Light public
        self.assertEqual(classify("Sunderland 100%", ["Sunderland"]), "PRIVATE")

    def test_the_german_land_still_matches(self):
        self.assertEqual(classify("Land Salzburg"), "PUBLIC")

    def test_county_alone_is_not_evidence_of_public_ownership(self):
        # in English a "County" is as often a club as an administrative area
        self.assertEqual(classify("Derby County F.C."), "PRIVATE")
        self.assertEqual(classify("Cluj County Council"), "PUBLIC")


class InflectedAndCompoundTests(SimpleTestCase):
    """Word boundaries must not break languages that inflect or compound."""

    def test_stems_still_match_inflected_forms(self):
        self.assertEqual(classify("Gençlik ve Spor Bakanlığı"), "PUBLIC")   # Turkish
        self.assertEqual(classify("Ankara Büyükşehir Belediyesi"), "PUBLIC")
        self.assertEqual(classify("Kaunas City Municipality"), "PUBLIC")

    def test_german_compounds_still_match(self):
        self.assertEqual(classify("Marktgemeinde Lustenau"), "PUBLIC")
        self.assertEqual(classify("Stadtgemeinde Wiener Neustadt"), "PUBLIC")


class MissingKeywordTests(SimpleTestCase):
    """Gaps that sent a public owner to the wrong side."""

    def test_ville_du_is_as_public_as_ville_de(self):
        # only "ville de "/"ville d'" were listed, so Le Mans' city-owned ground
        # was published as privately owned
        self.assertEqual(classify("Ville du Mans"), "PUBLIC")
        self.assertEqual(classify("Ville de Lens"), "PUBLIC")

    def test_russian_federal_subjects(self):
        self.assertEqual(classify("Rostov Oblast"), "PUBLIC")
        self.assertEqual(classify("Khabarovsk Krai"), "PUBLIC")


class UnknownIsAnAnswerTests(SimpleTestCase):
    """The old code returned PRIVATE for anything it could not parse."""

    def test_an_unparseable_owner_is_unknown_not_private(self):
        self.assertEqual(classify("Grand Troyes"), "UNKNOWN")
        self.assertEqual(classify("Qwerty Foundation for Things"), "UNKNOWN")

    def test_empty_is_unknown(self):
        self.assertEqual(classify(""), "UNKNOWN")
        self.assertEqual(classify(None), "UNKNOWN")
        self.assertEqual(classify("   "), "UNKNOWN")


class ClubNameEvidenceTests(SimpleTestCase):
    """Wikipedia records a club-owned ground's owner as the bare club name."""

    def test_a_bare_club_name_is_private_when_a_tenant_matches(self):
        self.assertEqual(classify("Everton", ["Everton"]), "PRIVATE")
        self.assertEqual(classify("Nottingham Forest", ["Nottingham Forest"]), "PRIVATE")

    def test_the_club_prefix_does_not_have_to_match(self):
        self.assertEqual(classify("Benfica", ["SL Benfica"]), "PRIVATE")
        self.assertEqual(classify("Barcelona", ["FC Barcelona"], "Barcelona"), "PRIVATE")

    def test_a_council_sharing_its_tenants_name_stays_public(self):
        # the dangerous case: the club is Manchester City, the owner is the COUNCIL
        self.assertEqual(
            classify("Manchester City Council", ["Manchester City"], "Manchester"),
            "PUBLIC")
        self.assertEqual(
            classify("City of Manchester", ["Manchester City"], "Manchester"), "PUBLIC")


class CityNameTests(SimpleTestCase):
    """A bare town name in the owner field: town, or club named after the town?"""

    def test_a_town_with_no_club_of_that_name_is_the_town(self):
        self.assertEqual(classify("Caen", ["SM Caen"], "Caen"), "PUBLIC")
        self.assertEqual(classify("Rzeszów", ["Stal Rzeszów"], "Rzeszów"), "PUBLIC")
        self.assertEqual(classify("Kópavogur", ["Breiðablik"], "Kópavogur"), "PUBLIC")

    def test_an_english_club_named_for_its_town_owns_its_ground(self):
        self.assertEqual(classify("Middlesbrough", ["Middlesbrough"], "Middlesbrough"),
                         "PRIVATE")
        self.assertEqual(classify("Watford", ["Watford"], "Watford"), "PRIVATE")

    def test_a_sovereign_state_is_public_even_when_a_club_shares_the_name(self):
        # Stade Louis-II is owned by Monaco the state, not by AS Monaco
        self.assertEqual(
            classify("Monaco — Wikidata P127: Monaco (sovereign state)",
                     ["AS Monaco"], "Monaco"),
            "PUBLIC")


class MixedTests(SimpleTestCase):
    """The reported bug: a public owner AND a private one is MIXED, not either."""

    def test_public_body_plus_private_concession_is_mixed(self):
        self.assertEqual(
            classify("Ipswich Borough Council own the land only. "
                     "Stadium owned by Ipswich Town F.C."),
            "MIXED")

    def test_a_lease_from_the_owner_does_not_by_itself_make_it_mixed(self):
        self.assertEqual(classify("Hull City Council"), "PUBLIC")
