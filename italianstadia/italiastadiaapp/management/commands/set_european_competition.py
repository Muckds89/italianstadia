"""
set_european_competition
========================
Record which UEFA club competition each club is in this season, so the export can
draw continental maps (`?uefa=UCL`, `?color_by=uefa`).

WHEN TO RUN THIS
----------------
Only once the LEAGUE PHASE DRAWS are made — late August. Before that the field
should stay empty, because during qualifying a club's competition is not yet a
fact: losers of the Champions League play-off round drop into the Europa League,
and Europa League play-off losers drop into the Conference League. A club can
therefore appear in a "participants" list for a competition it will not play in.

That is not a hypothetical. Asked for the 2026/27 Champions League league phase in
August 2026, one summary confidently returned 36 clubs including Viking, NEC and
LASK; the article itself said the phase "has not been drawn" and listed qualifying
fixtures. Writing that would have published a wrong Champions League map.

INPUT
-----
A JSON file mapping competition -> list of club names, e.g.

    {
      "UCL":  ["Arsenal", "Real Madrid", "Inter Milan", ...],
      "UEL":  ["AS Roma", "Real Betis", ...],
      "UECL": ["Fiorentina", ...]
    }

Names are matched against Team.name, transliterated and punctuation-stripped, so
"Atlético Madrid" matches "Atlético de Madrid". Anything that does not match
EXACTLY ONE club is reported and skipped — never guessed, because assigning a
competition to the wrong club is the kind of error nobody spots on a map.

    python -X utf8 manage.py set_european_competition scripts/data/uefa_2026_27.json
    python -X utf8 manage.py set_european_competition <file> --fix
    python -X utf8 manage.py set_european_competition --clear --fix
"""
import json
import re
import unicodedata
from collections import defaultdict

from django.core.management.base import BaseCommand, CommandError

from italiastadiaapp.models import Team

VALID = {"UCL", "UEL", "UECL"}


def norm(s):
    s = unicodedata.normalize("NFKD", (s or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    # drop the corporate furniture clubs carry inconsistently between sources
    s = re.sub(r"\b(fc|afc|cf|sc|ac|as|ss|us|uc|sk|fk|nk|hnk|gnk|bk|if|ff|"
               r"club|calcio|futbol|football|de|the)\b", " ", s)
    return re.sub(r"[^a-z0-9]", "", s)


class Command(BaseCommand):
    help = "Set Team.european_competition from a competition -> clubs JSON file."

    def add_arguments(self, p):
        p.add_argument("path", nargs="?", default="",
                       help="JSON file of {competition: [club names]}")
        p.add_argument("--fix", action="store_true", help="write changes")
        p.add_argument("--clear", action="store_true",
                       help="blank the field on every club first (new season)")

    def handle(self, *a, **o):
        if o["clear"]:
            n = Team.objects.exclude(european_competition="").count()
            if o["fix"]:
                Team.objects.exclude(european_competition="").update(european_competition="")
            self.stdout.write(self.style.WARNING(
                f"{'cleared' if o['fix'] else 'would clear'} {n} club(s)"))
            if not o["path"]:
                return

        if not o["path"]:
            raise CommandError("give a JSON file, or use --clear on its own")
        try:
            data = json.load(open(o["path"], encoding="utf-8"))
        except Exception as e:
            raise CommandError(f"cannot read {o['path']}: {e}")

        bad = set(data) - VALID
        if bad:
            raise CommandError(f"unknown competition key(s): {sorted(bad)}; "
                               f"expected {sorted(VALID)}")

        # index every club once; a name that hits two clubs is ambiguous, not a match
        index = defaultdict(list)
        for t in Team.objects.exclude(is_national=True):
            index[norm(t.name)].append(t)

        assigned, missing, ambiguous, conflicts = 0, [], [], []
        seen = {}
        for comp, names in data.items():
            for name in names:
                hits = index.get(norm(name), [])
                if not hits:
                    missing.append(f"{comp}: {name}")
                    continue
                if len(hits) > 1:
                    ambiguous.append(f"{comp}: {name} -> {[t.name for t in hits]}")
                    continue
                t = hits[0]
                if t.pk in seen and seen[t.pk] != comp:
                    conflicts.append(f"{t.name}: listed in both {seen[t.pk]} and {comp}")
                    continue
                seen[t.pk] = comp
                if t.european_competition != comp:
                    if o["fix"]:
                        t.european_competition = comp
                        t.save(update_fields=["european_competition"])
                    assigned += 1

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(
            f"{'set' if o['fix'] else 'would set'} {assigned} club(s); "
            f"{len(seen)} matched of {sum(len(v) for v in data.values())} listed"))
        for label, rows in (("NOT FOUND", missing), ("AMBIGUOUS", ambiguous),
                            ("CONFLICT", conflicts)):
            for r in rows:
                self.stdout.write(self.style.ERROR(f"  {label}  {r}"))
        if missing or ambiguous or conflicts:
            self.stdout.write(self.style.WARNING(
                "\nUnmatched clubs are SKIPPED, never guessed. Fix the names in the "
                "JSON (they must match Team.name) and re-run."))
        if o["fix"]:
            self.stdout.write(self.style.WARNING(
                "\nRe-dump the fixture and regenerate stadiums_map.json."))
