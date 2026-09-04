"""
A club's DOMESTIC ground and its EUROPEAN ground are two different facts.

Two readers caught this on the same published Conference League map, within hours
of each other:

  - AGF Aarhus are in a temporary modular ground while Kongelunden is built. It is
    not licensed for UEFA matches, so they host Europe at Cepheus Park Randers --
    the ground of their rivals Randers FC, who are not in the competition at all.
  - Mjallby AIF host at Olympia in Helsingborg, 147km from Strandvallen, because
    Strandvallen is not approved for European matches either.

The export was stadium-first and joined on TENANCY: `Stadium.objects.filter(
teams__european_competition=...)`. A displaced club is not a tenant of the ground
it borrows, so that join could only ever return the club's domestic ground. Both
clubs were drawn in the wrong city and nothing anywhere reported a problem -- the
map was internally consistent and externally wrong, which is the failure mode this
project keeps meeting.

`Team.uefa_stadium` records the exception; null means "the usual ground". The
export resolves club -> venue FIRST and selects venues from that, so a displaced
club moves and, critically, does NOT also remain at home.
"""
from django.test import TestCase

from italiastadiaapp.models import City, Country, League, Stadium, Team
from italiastadiaapp.views import _get_export_stadiums


def _params(**over):
    """A full export param dict -- the view reads every key unconditionally."""
    p = {"country": "", "league": "", "surface": "", "ownership": "",
         "stadium_type": "", "surface_known": False, "uefa": "", "national": False,
         "national_only": False, "no_badges": False}
    p.update(over)
    return p


class UefaVenueTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        # get_or_create throughout: the test database is seeded from the
        # project fixture, so the real countries and many league names are
        # already present and plain create() collides on their unique keys.
        dk, _ = Country.objects.get_or_create(name="Denmark",
                                              defaults={"code": "DK"})
        cls.league = League.objects.create(name="UefaVenueTest Superliga",
                                           country=dk, division_level=1)
        aarhus = City.objects.create(name="UefaVenueTest Aarhus", country="Denmark")
        randers = City.objects.create(name="UefaVenueTest Randers", country="Denmark")

        cls.temporary = Stadium.objects.create(
            name="UefaVenueTest Ceres Park Vejlby", city=aarhus, capacity=12000,
            latitude="56.192390", longitude="10.210301")
        cls.borrowed = Stadium.objects.create(
            name="UefaVenueTest Cepheus Park Randers", city=randers, capacity=10300,
            latitude="56.465940", longitude="10.010262")

        # The club that has to move, and the club whose ground it borrows. The
        # host is NOT in the competition -- that is what makes the label wrong if
        # the tenants are not narrowed.
        cls.agf = Team.objects.create(
            name="UefaVenueTest AGF", city=aarhus, league=cls.league,
            tier=1, stadium=cls.temporary, uefa_stadium=cls.borrowed,
            european_competition="UECL")
        cls.host = Team.objects.create(
            name="UefaVenueTest Randers FC", city=randers, league=cls.league, tier=1,
            stadium=cls.borrowed)

    def _uecl(self):
        return _get_export_stadiums(_params(uefa="UECL"))

    def test_the_club_is_drawn_at_the_ground_it_actually_uses(self):
        names = [s["name"] for s in self._uecl()]
        self.assertIn("UefaVenueTest Cepheus Park Randers", names)

    def test_the_club_is_NOT_also_drawn_at_its_domestic_ground(self):
        """The bug that reaches the reader is the club appearing in the wrong city.

        The bug that would reach them NEXT is it appearing in both, so assert the
        move is a move and not a duplication.
        """
        names = [s["name"] for s in self._uecl()]
        self.assertNotIn("UefaVenueTest Ceres Park Vejlby", names)
        self.assertEqual(len(names), 1)

    def test_the_borrowed_ground_is_labelled_with_the_VISITING_club(self):
        """Cepheus Park is Randers FC's ground, and Randers are not in Europe.

        Labelling it with its own tenant would name a club that is not in the
        competition, on a map of that competition -- the same mistake already
        fixed for groundshares like Cercle and Club Brugge.
        """
        row = self._uecl()[0]
        self.assertEqual(row["team_name"], "UefaVenueTest AGF")
        self.assertEqual([t["name"] for t in row["teams"]],
                         ["UefaVenueTest AGF"])

    def test_the_marker_takes_the_visiting_club_competition(self):
        """Colour comes from the competition; the host tenant has none."""
        self.assertEqual(self._uecl()[0]["european_competition"], "UECL")

    def test_a_club_with_no_uefa_stadium_is_untouched(self):
        """Null must mean "the usual ground", not "no ground"."""
        self.agf.uefa_stadium = None
        self.agf.save(update_fields=["uefa_stadium"])
        names = [s["name"] for s in self._uecl()]
        self.assertEqual(names, ["UefaVenueTest Ceres Park Vejlby"])

    def test_the_domestic_map_still_shows_the_domestic_ground(self):
        """uefa_stadium is read ONLY on the UEFA path.

        A league map of the Superliga must still put AGF in Aarhus, and must still
        show Randers at their own ground.
        """
        names = sorted(s["name"] for s in
                       _get_export_stadiums(_params(league="UefaVenueTest Superliga")))
        self.assertEqual(names, ["UefaVenueTest Cepheus Park Randers", "UefaVenueTest Ceres Park Vejlby"])


class UefaVenueAbroadTests(TestCase):
    """A displaced club often hosts in another COUNTRY.

    Country highlighting joins on the club's federation, deliberately, rather than
    asking which polygon contains the dot. A club exiled abroad is the case where
    those two answers differ most: the marker sits in the host country while the
    association that qualified is somewhere else entirely.
    """

    @classmethod
    def setUpTestData(cls):
        ua, _ = Country.objects.get_or_create(name="Ukraine",
                                              defaults={"code": "UA"})
        en, _ = Country.objects.get_or_create(name="England",
                                              defaults={"code": "GB"})
        cls.upl = League.objects.create(name="UefaVenueTest UPL",
                                        country=ua, division_level=1)
        epl = League.objects.create(name="UefaVenueTest EPL",
                                    country=en, division_level=1)
        kyiv = City.objects.create(name="UefaVenueTest Kyiv", country="Ukraine")
        london = City.objects.create(name="UefaVenueTest London", country="England")

        home = Stadium.objects.create(name="UefaVenueTest Home Ground", city=kyiv, capacity=70000,
                                      latitude="50.433333", longitude="30.521944")
        away = Stadium.objects.create(name="UefaVenueTest Borrowed Ground", city=london,
                                      capacity=40000, latitude="51.481667",
                                      longitude="-0.191111")
        Team.objects.create(name="UefaVenueTest Host FC", city=london, league=epl, tier=1,
                            stadium=away)
        cls.exiled = Team.objects.create(
            name="UefaVenueTest Exiled FC", city=kyiv, league=cls.upl, tier=1, stadium=home,
            uefa_stadium=away, european_competition="UCL")

    def test_the_federation_is_the_exiled_club_not_the_host_ground(self):
        rows = _get_export_stadiums(_params(uefa="UCL"))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "UefaVenueTest Borrowed Ground")
        self.assertEqual(rows[0]["federation"], "Ukraine")


class UefaGroundshareFederationTests(TestCase):
    """A shared ground answers with the federation of the club IN the competition.

    Estadi de la FAF is used by Inter Club d'Escaldes, who play in the Andorran
    Primera Divisio, and by FC Andorra, who play in the SPANISH Segunda. The
    federation was taken from whichever tenant the ground happened to list first,
    so a Conference League map lit up SPAIN for a ground whose only club in the
    competition is Andorran -- and left Andorra dark, on the very map that had
    just been extended to include Andorra so that every competition showed 36.
    """

    @classmethod
    def setUpTestData(cls):
        ad, _ = Country.objects.get_or_create(name="Andorra",
                                              defaults={"code": "AD"})
        es, _ = Country.objects.get_or_create(name="Spain", defaults={"code": "ES"})
        home = League.objects.create(name="UefaVenueTest Primera Divisio",
                                     country=ad, division_level=1)
        abroad = League.objects.create(name="UefaVenueTest Segunda",
                                       country=es, division_level=2)
        city = City.objects.create(name="UefaVenueTest Encamp", country="Andorra")
        ground = Stadium.objects.create(
            name="UefaVenueTest Estadi de la FAF", city=city, capacity=5600,
            latitude="42.536111", longitude="1.583333")

        # Created FIRST, so it leads s.teams.all() and wins a naive lookup.
        Team.objects.create(name="UefaVenueTest FC Andorra", city=city,
                            league=abroad, tier=2, stadium=ground)
        Team.objects.create(name="UefaVenueTest Inter Escaldes", city=city,
                            league=home, tier=1, stadium=ground,
                            european_competition="UECL")

    def test_federation_comes_from_the_club_in_the_competition(self):
        rows = _get_export_stadiums(_params(uefa="UECL"))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["federation"], "Andorra")

    def test_the_label_names_only_the_club_in_the_competition(self):
        rows = _get_export_stadiums(_params(uefa="UECL"))
        self.assertEqual([t["name"] for t in rows[0]["teams"]],
                         ["UefaVenueTest Inter Escaldes"])
