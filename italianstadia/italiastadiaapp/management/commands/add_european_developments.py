"""
add_european_developments
=========================
Seeds the StadiumDevelopment table with confirmed under-development
stadium projects outside Italy (Italian ones already populated).

Safe to run multiple times — uses get_or_create on name.

Usage:
    python manage.py add_european_developments
    python manage.py add_european_developments --dry-run
"""

from django.core.management.base import BaseCommand

PROJECTS = [
    # ── Spain ────────────────────────────────────────────────────────────────
    {
        "name": "Nou Estadi del FC Barcelona (Espai Barça)",
        "project_type": "REDEVELOPMENT",
        "status": "UNDER_CONSTRUCTION",
        "future_capacity": 105000,
        "estimated_opening": 2026,
        "latitude": 41.3809,
        "longitude": 2.1228,
        "architect": "Populous / Pinearq",
        "developer": "FC Barcelona",
        "source_url": "https://en.wikipedia.org/wiki/Spotify_Camp_Nou",
        "notes": "Espai Barça project. Full renovation of Camp Nou retaining the shell. Retractable roof and new roof structure. Europe's largest football stadium when complete.",
    },
    # ── Italy ────────────────────────────────────────────────────────────────
    {
        "name": "New San Siro (La Maura)",
        "project_type": "NEW",
        "status": "APPROVED",
        "future_capacity": 70000,
        "estimated_opening": 2028,
        "latitude": 45.4929,
        "longitude": 9.0920,
        "architect": "Populous",
        "developer": "AC Milan / FC Internazionale Milano",
        "source_url": "https://en.wikipedia.org/wiki/New_San_Siro",
        "notes": "New shared ground for AC Milan and Inter Milan to replace Giuseppe Meazza. Located at La Maura horse-racing track site, ~1.5km from current San Siro.",
    },
    # ── England ──────────────────────────────────────────────────────────────
    {
        "name": "New Stamford Bridge",
        "project_type": "NEW",
        "status": "PLANNING",
        "future_capacity": 60000,
        "estimated_opening": 2032,
        "latitude": 51.4816,
        "longitude": -0.1909,
        "architect": "Herzog & de Meuron",
        "developer": "Chelsea FC / Blueco",
        "source_url": "https://en.wikipedia.org/wiki/Stamford_Bridge_(stadium)",
        "notes": "Complete rebuild on the existing Stamford Bridge footprint. Project has faced planning delays. Previous rebuild designs rejected; current scheme by Herzog & de Meuron.",
    },
    {
        "name": "Molineux Stadium Expansion",
        "project_type": "EXPANSION",
        "status": "APPROVED",
        "future_capacity": 50000,
        "estimated_opening": 2027,
        "latitude": 52.5902,
        "longitude": -2.1302,
        "architect": None,
        "developer": "Wolverhampton Wanderers FC",
        "source_url": "https://en.wikipedia.org/wiki/Molineux_Stadium",
        "notes": "North Stand rebuild and South Stand expansion to take capacity from 31,750 to ~50,000.",
    },
    {
        "name": "Selhurst Park Expansion",
        "project_type": "EXPANSION",
        "status": "UNDER_CONSTRUCTION",
        "future_capacity": 34000,
        "estimated_opening": 2026,
        "latitude": 51.3983,
        "longitude": -0.0856,
        "architect": "KSS Architects",
        "developer": "Crystal Palace FC",
        "source_url": "https://en.wikipedia.org/wiki/Selhurst_Park",
        "notes": "New Main Stand replacing the existing Holmesdale Road end. Increases capacity from 25,486 to approximately 34,000.",
    },
    {
        "name": "Bramall Lane Expansion",
        "project_type": "EXPANSION",
        "status": "PLANNING",
        "future_capacity": 40000,
        "estimated_opening": 2028,
        "latitude": 53.3703,
        "longitude": -1.4706,
        "architect": None,
        "developer": "Sheffield United FC",
        "source_url": "https://en.wikipedia.org/wiki/Bramall_Lane",
        "notes": "Plans to rebuild the South Stand and expand overall capacity from 32,702 to ~40,000.",
    },
    {
        "name": "Celtic Park Expansion",
        "project_type": "EXPANSION",
        "status": "PLANNING",
        "future_capacity": 63000,
        "estimated_opening": 2030,
        "latitude": 55.8493,
        "longitude": -4.2058,
        "architect": None,
        "developer": "Celtic FC",
        "source_url": "https://en.wikipedia.org/wiki/Celtic_Park",
        "notes": "Long-discussed expansion of Celtic Park to ~63,000 to make it the largest club stadium in the UK. Planning and funding details ongoing.",
    },
    # ── Netherlands ──────────────────────────────────────────────────────────
    {
        "name": "Nieuw Feyenoord Stadion",
        "project_type": "NEW",
        "status": "APPROVED",
        "future_capacity": 63000,
        "estimated_opening": 2028,
        "latitude": 51.8850,
        "longitude": 4.5200,
        "architect": "Populous",
        "developer": "Feyenoord Rotterdam",
        "source_url": "https://en.wikipedia.org/wiki/Feyenoord_City",
        "notes": "New stadium to replace De Kuip, part of the Feyenoord City urban regeneration project on the bank of the Maas river in Rotterdam-Zuid.",
    },
    # ── Germany ──────────────────────────────────────────────────────────────
    {
        "name": "Signal Iduna Park – East/West Stand Expansion",
        "project_type": "EXPANSION",
        "status": "PLANNING",
        "future_capacity": 92000,
        "estimated_opening": 2029,
        "latitude": 51.4926,
        "longitude": 7.4518,
        "architect": None,
        "developer": "Borussia Dortmund",
        "source_url": "https://en.wikipedia.org/wiki/Westfalenstadion",
        "notes": "Plans to expand the East and West stands. The South Stand (Südtribüne / Yellow Wall) at 24,454 standing is already the largest standing terrace in world football.",
    },
    {
        "name": "Volksparkstadion Renovation",
        "project_type": "REDEVELOPMENT",
        "status": "PLANNING",
        "future_capacity": 65000,
        "estimated_opening": 2028,
        "latitude": 53.5875,
        "longitude": 9.8987,
        "architect": None,
        "developer": "Hamburger SV / HSH Nordbank Arena",
        "source_url": "https://en.wikipedia.org/wiki/Volksparkstadion",
        "notes": "Major renovation planned of the Volksparkstadion. HSV aim to modernise facilities and increase capacity to compete following potential return to Bundesliga.",
    },
    # ── France ───────────────────────────────────────────────────────────────
    {
        "name": "Nouveau Parc des Princes",
        "project_type": "REDEVELOPMENT",
        "status": "PLANNING",
        "future_capacity": 65000,
        "estimated_opening": 2030,
        "latitude": 48.8414,
        "longitude": 2.2530,
        "architect": None,
        "developer": "Paris Saint-Germain FC / City of Paris",
        "source_url": "https://en.wikipedia.org/wiki/Parc_des_Princes",
        "notes": "PSG have long sought to either buy Parc des Princes from the City of Paris or build a new stadium. Major expansion/rebuild plans tied to ongoing ownership negotiations.",
    },
    # ── Portugal ─────────────────────────────────────────────────────────────
    {
        "name": "Novo Estádio do Sporting CP",
        "project_type": "NEW",
        "status": "PLANNING",
        "future_capacity": 50000,
        "estimated_opening": 2030,
        "latitude": 38.7612,
        "longitude": -9.1609,
        "architect": None,
        "developer": "Sporting CP",
        "source_url": "https://en.wikipedia.org/wiki/Est%C3%A1dio_Jos%C3%A9_Alvalade",
        "notes": "Sporting CP have explored plans for a new larger stadium to replace or significantly expand the current José Alvalade (50,095). Plans at early feasibility stage.",
    },
    # ── Belgium ──────────────────────────────────────────────────────────────
    {
        "name": "National Football Stadium Belgium",
        "project_type": "NEW",
        "status": "PLANNING",
        "future_capacity": 62000,
        "estimated_opening": 2029,
        "latitude": 50.9010,
        "longitude": 4.3840,
        "architect": None,
        "developer": "Royal Belgian Football Association / Ghelamco",
        "source_url": "https://en.wikipedia.org/wiki/Eurostadium",
        "notes": "Belgium's Eurostadium project: a new national stadium to replace the King Baudouin Stadium (Stade Roi Baudouin). Multiple sites and developers considered over several years.",
    },
    # ── Poland ───────────────────────────────────────────────────────────────
    {
        "name": "Legia Warsaw – New Stadium",
        "project_type": "NEW",
        "status": "PLANNING",
        "future_capacity": 45000,
        "estimated_opening": 2030,
        "latitude": 52.2203,
        "longitude": 20.9991,
        "architect": None,
        "developer": "Legia Warsaw",
        "source_url": "https://en.wikipedia.org/wiki/Polish_Army_Stadium",
        "notes": "Legia have studied plans to build a new stadium or significantly rebuild the Wojska Polskiego to increase capacity from 31,800.",
    },
    # ── Turkey ───────────────────────────────────────────────────────────────
    {
        "name": "Galatasaray Yeni Stadyum",
        "project_type": "NEW",
        "status": "APPROVED",
        "future_capacity": 52000,
        "estimated_opening": 2027,
        "latitude": 41.0600,
        "longitude": 29.0200,
        "architect": None,
        "developer": "Galatasaray SK",
        "source_url": "https://en.wikipedia.org/wiki/Galatasaray_S.K.",
        "notes": "Galatasaray plan to build a new stadium in Istanbul to replace or supplement Rams Park (Nef Stadyumu), targeting larger capacity for domestic and European matches.",
    },
]


class Command(BaseCommand):
    help = "Seeds European under-development stadium projects into StadiumDevelopment."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Print what would be created without saving.")

    def handle(self, *args, **options):
        from italiastadiaapp.models import StadiumDevelopment

        dry_run = options["dry_run"]
        created_count = 0
        skipped_count = 0

        for p in PROJECTS:
            if dry_run:
                exists = StadiumDevelopment.objects.filter(name=p["name"]).exists()
                flag = "EXISTS" if exists else "WOULD CREATE"
                self.stdout.write(f"  [{flag}] {p['name']} ({p['future_capacity']:,} cap)")
                if not exists:
                    created_count += 1
                continue

            obj, created = StadiumDevelopment.objects.get_or_create(
                name=p["name"],
                defaults={
                    "project_type":      p["project_type"],
                    "status":            p["status"],
                    "future_capacity":   p["future_capacity"],
                    "estimated_opening": p["estimated_opening"],
                    "latitude":          p["latitude"],
                    "longitude":         p["longitude"],
                    "architect":         p.get("architect") or "",
                    "developer":         p.get("developer") or "",
                    "source_url":        p.get("source_url") or "",
                    "notes":             p.get("notes") or "",
                },
            )
            if created:
                created_count += 1
                self.stdout.write(self.style.SUCCESS(f"  Created: {obj.name}"))
            else:
                skipped_count += 1
                self.stdout.write(f"  Skipped (exists): {obj.name}")

        self.stdout.write(self.style.SUCCESS(
            f"\nDone. Created: {created_count} | Skipped: {skipped_count}"
        ))
        if not dry_run and created_count:
            self.stdout.write(self.style.WARNING(
                "\nRemember to regenerate the fixture:\n"
                "  python manage.py dumpdata --natural-foreign --natural-primary "
                "--indent 2 > italiastadiaapp/fixtures/initial_data.json"
            ))
