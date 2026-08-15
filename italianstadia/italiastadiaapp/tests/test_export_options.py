"""
League dropdown grouping on the export page.

Leagues were grouped by the country their clubs' GROUNDS sit in, which is not the
same as the country that runs the competition. The New Saints are a Cymru Premier
club who play at Park Hall in Oswestry, England -- one club, and the entire Welsh
league appeared in England's dropdown.

It was never just Wales: Cardiff, Swansea and Wrexham put the EFL Championship
under Wales, Vaduz put the Swiss Super League under Liechtenstein, Derry City put
the League of Ireland under Northern Ireland, and FC Andorra put the Segunda
División under Andorra. Selecting any of those drew a map of two or three clubs.

A league is now offered under whichever country holds MOST of its grounds. The
keys stay `city.country` free text because that is what the export filter matches
on -- keying off the Country model would break countries whose two spellings
differ ("Czechia" vs "Czech Republic").
"""
from django.test import TestCase
from django.urls import reverse

from italiastadiaapp.models import City, Country, League, Stadium, Team


class LeagueGroupingTests(TestCase):

    # Fictional countries: the test database is loaded from the project fixture,
    # so asserting on real ones would be measuring the shipped data rather than
    # the grouping rule.
    HOME, NEIGHBOUR = "Testland", "Nextdoor"

    @classmethod
    def setUpTestData(cls):
        home = Country.objects.create(name="Testland", code="T1")
        nb = Country.objects.create(name="Nextdoor", code="T2")
        cls.home_league = League.objects.create(name="Testland Premier",
                                                country=home, division_level=1)
        cls.nb_league = League.objects.create(name="Nextdoor Championship",
                                              country=nb, division_level=2)
        cls.home_city = City.objects.create(name="Testville", country=cls.HOME)
        cls.nb_city = City.objects.create(name="Borderton", country=cls.NEIGHBOUR)

        def club(name, league, city):
            s = Stadium.objects.create(name=f"{name} Ground", city=city,
                                       latitude=52.0, longitude=-3.0)
            return Team.objects.create(name=name, league=league, stadium=s, city=city)

        # eleven grounds at home, one across the border (the New Saints case)
        for i in range(11):
            club(f"Home Club {i}", cls.home_league, cls.home_city)
        club("Border Saints", cls.home_league, cls.nb_city)
        # and the mirror: a neighbour league holding three of our clubs
        for i in range(21):
            club(f"Nb Club {i}", cls.nb_league, cls.nb_city)
        for i in range(3):
            club(f"Expat Club {i}", cls.nb_league, cls.home_city)

    def _groups(self):
        r = self.client.get(reverse("italiastadiaapp:export_options"))
        self.assertEqual(r.status_code, 200)
        return r.json()["leagues_by_country"]

    def test_one_ground_across_the_border_does_not_move_a_league(self):
        self.assertNotIn("Testland Premier", self._groups().get(self.NEIGHBOUR, []))

    def test_league_is_offered_under_the_country_that_runs_it(self):
        self.assertIn("Testland Premier", self._groups().get(self.HOME, []))

    def test_symmetric_case_english_league_is_not_offered_under_wales(self):
        # Cardiff, Swansea and Wrexham are real EFL clubs but do not make it Welsh
        self.assertNotIn("Nextdoor Championship", self._groups().get(self.HOME, []))
        self.assertIn("Nextdoor Championship", self._groups().get(self.NEIGHBOUR, []))

    def test_hidden_leagues_are_never_offered(self):
        self.home_league.hidden = True
        self.home_league.save(update_fields=["hidden"])
        self.assertNotIn("Testland Premier", self._groups().get(self.HOME, []))

    def test_a_genuine_tie_lists_the_league_under_both(self):
        # nothing in the data ties today, but a cross-border league must not vanish
        for i in range(8):
            s = Stadium.objects.create(name=f"Tie Ground {i}", city=self.home_city,
                                       latitude=52.0, longitude=-3.0)
            Team.objects.create(name=f"Tie Club {i}", league=self.home_league,
                                stadium=s, city=self.home_city)
        # Wales 19 vs England 1 -- still Wales; now force parity
        for i in range(18):
            s = Stadium.objects.create(name=f"Tie Eng {i}", city=self.nb_city,
                                       latitude=52.0, longitude=-3.0)
            Team.objects.create(name=f"Tie Eng Club {i}", league=self.home_league,
                                stadium=s, city=self.nb_city)
        g = self._groups()
        self.assertIn("Testland Premier", g.get(self.HOME, []))
        self.assertIn("Testland Premier", g.get(self.NEIGHBOUR, []))
