"""
Seed UEFA Euro 2028 and 2032 tournament data onto known venue stadiums.
Safe to re-run — uses force=False by default (skips already-filled entries).
"""
from django.core.management.base import BaseCommand

from italiastadiaapp.models import Stadium

TOURNAMENT_SEEDS = [
    # --- UEFA Euro 2028 (UK & Ireland) ---
    # id, tournament name, year, status, matches
    (193, "UEFA Euro 2028", 2028, "CONFIRMED", 6),   # Tottenham Hotspur Stadium, London
    (195, "UEFA Euro 2028", 2028, "CONFIRMED", 5),   # Villa Park, Birmingham
    (194, "UEFA Euro 2028", 2028, "CONFIRMED", 5),   # St. James' Park, Newcastle
    (407, "UEFA Euro 2028", 2028, "CONFIRMED", 4),   # Bramall Lane, Sheffield
    (592, "UEFA Euro 2028", 2028, "CANDIDATE", None),  # Cardiff City Stadium
    (283, "UEFA Euro 2028", 2028, "CANDIDATE", None),  # Celtic Park, Glasgow

    # --- UEFA Euro 2032 (Italy & Turkey) ---
    (8,   "UEFA Euro 2032", 2032, "CONFIRMED", 7),   # Giuseppe Meazza (San Siro), Milan
    (34,  "UEFA Euro 2032", 2032, "CONFIRMED", 6),   # Olimpico di Roma, Rome
    (35,  "UEFA Euro 2032", 2032, "CONFIRMED", 5),   # Diego Armando Maradona, Naples
    (32,  "UEFA Euro 2032", 2032, "CONFIRMED", 5),   # Allianz Stadium, Turin
    (56,  "UEFA Euro 2032", 2032, "CONFIRMED", 4),   # San Nicola, Bari
    (38,  "UEFA Euro 2032", 2032, "CONFIRMED", 4),   # Artemio Franchi, Florence
    (299, "UEFA Euro 2032", 2032, "CONFIRMED", 7),   # Atatürk Olimpiyat, Istanbul
    (301, "UEFA Euro 2032", 2032, "CONFIRMED", 5),   # RAMS Park, Istanbul
    (300, "UEFA Euro 2032", 2032, "CONFIRMED", 5),   # Şükrü Saracoğlu, Istanbul
    (296, "UEFA Euro 2032", 2032, "CANDIDATE", None),  # Beşiktaş Park, Istanbul
]


class Command(BaseCommand):
    help = "Seed Euro 2028/2032 tournament data onto venue stadiums"

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true",
                            help="Overwrite existing tournament entries")

    def handle(self, *args, **options):
        force = options["force"]
        updated = skipped = missing = 0

        for stadium_id, tournament, year, status, matches in TOURNAMENT_SEEDS:
            try:
                s = Stadium.objects.get(pk=stadium_id)
            except Stadium.DoesNotExist:
                self.stderr.write(f"  MISSING id={stadium_id} ({tournament})")
                missing += 1
                continue

            # Check if this tournament entry already exists
            existing = [
                t for t in s.tournaments
                if t.get("tournament") == tournament
            ]
            if existing and not force:
                skipped += 1
                continue

            # Remove old entry for this tournament then append fresh one
            entry = {"tournament": tournament, "year": year, "status": status}
            if matches is not None:
                entry["matches"] = matches

            s.tournaments = [t for t in s.tournaments if t.get("tournament") != tournament]
            s.tournaments.append(entry)
            Stadium.objects.filter(pk=s.pk).update(tournaments=s.tournaments)
            self.stdout.write(f"  {status}: {s.name} → {tournament}")
            updated += 1

        self.stdout.write(self.style.SUCCESS(
            f"\nDone: {updated} updated, {skipped} skipped, {missing} missing"
        ))
