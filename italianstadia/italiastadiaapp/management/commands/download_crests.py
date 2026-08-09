"""
download_crests
===============
Store every club crest locally so a map render makes NO network call for badges.

Crests used to be pulled from a third party at render time. Transfermarkt then
soft-blocked us (HTTP 200, zero bytes) and killed 999 of 1,034 badges, and
Wikimedia -- the replacement -- throttles bursts. Both failures are silent: a
missing crest renders as a plain dot, which reads as a design choice rather than
an error, so maps were published with bare dots before anyone noticed.

Everything is normalised to PNG at _BADGE_FETCH_SIZE:
  * SVGs are rasterised ONCE here instead of through the MediaWiki thumbnail API
    on every cold start, which takes that call off the render path entirely
  * one format means the renderer never branches on file type
  * the file is pre-fitted through _fit_badge_in_circle, so the circular badge
    mask cannot clip it later

Files land in static/crests/<team-slug>.png and are committed. This is the same
pattern the project already uses for stadiums_map.json and the tournament PNGs:
pre-generate, commit, serve statically, because the free tier cannot be trusted to
do work at request time.

Usage:
    python -X utf8 manage.py download_crests                 # only what is missing
    python -X utf8 manage.py download_crests --force         # re-download all
    python -X utf8 manage.py download_crests --league "Serie A"
"""
import time
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from italiastadiaapp.models import Team


class Command(BaseCommand):
    help = "Download every club crest into static/crests/ and record it on the team."

    def add_arguments(self, p):
        p.add_argument("--force", action="store_true",
                       help="re-download even if the file already exists")
        p.add_argument("--league", default="", help="limit to one league name")
        p.add_argument("--sleep", type=float, default=0.15,
                       help="pause between downloads; the per-host cap still applies")

    # SVG -> rasterised PNG, resolved in BATCHES.
    #
    # _svg_badge_png_url asks the MediaWiki API about one file per call. Across ~600
    # SVGs that is 600 rapid requests, Wikimedia throttles, the resolver's bare
    # except swallows it and every one of those crests fails silently. 613 of 997
    # died that way on the first full run. The API takes 50 titles at a time, which
    # is ~13 calls instead of 600.
    @staticmethod
    def _resolve_svgs(urls, sleep):
        import requests
        from collections import defaultdict
        from urllib.parse import unquote

        from italiastadiaapp.views import _BADGE_UA_WIKIMEDIA

        by_host = defaultdict(dict)          # host -> {File:title: original url}
        for u in urls:
            proj = "commons"
            if "/wikipedia/" in u:
                proj = u.split("/wikipedia/", 1)[1].split("/", 1)[0]
            host = ("commons.wikimedia.org" if proj == "commons"
                    else f"{proj}.wikipedia.org")
            # Underscores must become spaces. MediaWiki accepts the underscored
            # form but ECHOES BACK the normalised title with spaces, so keying on
            # the underscored string made every lookup miss and the batch resolved
            # 0 of 15 while silently falling through to per-file calls.
            title = "File:" + unquote(u.rsplit("/", 1)[-1]).replace("_", " ")
            by_host[host][title] = u

        out = {}
        for host, titles in by_host.items():
            keys = list(titles)
            for i in range(0, len(keys), 50):
                batch = keys[i:i + 50]
                try:
                    r = requests.get(
                        f"https://{host}/w/api.php", timeout=40,
                        headers={"User-Agent": _BADGE_UA_WIKIMEDIA},
                        params={"action": "query", "format": "json",
                                "formatversion": "2", "titles": "|".join(batch),
                                "prop": "imageinfo", "iiprop": "url",
                                "iiurlwidth": 256})
                    time.sleep(sleep)
                    data = r.json()
                except Exception:
                    continue          # leave this batch unresolved; reported below
                for page in data.get("query", {}).get("pages", []):
                    ii = (page.get("imageinfo") or [{}])[0]
                    thumb = ii.get("thumburl")
                    src = titles.get(page.get("title"))
                    if thumb and src:
                        out[src] = thumb
        return out

    def handle(self, *a, **o):
        from italiastadiaapp.views import _BADGE_FETCH_SIZE, _fetch_badge_image

        out_dir = Path(settings.BASE_DIR) / "italiastadiaapp" / "static" / "crests"
        out_dir.mkdir(parents=True, exist_ok=True)

        qs = Team.objects.exclude(is_national=True).exclude(
            image_url="").exclude(image_url__isnull=True)
        if o["league"]:
            qs = qs.filter(league__name=o["league"])
        qs = list(qs.order_by("name"))

        pending = [t for t in qs
                   if o["force"] or not (out_dir / f"{t.slug}.png").exists()]
        svgs = sorted({t.image_url for t in pending
                       if (t.image_url or "").lower().split("?")[0].endswith(".svg")})
        svg_png = {}
        if svgs:
            self.stdout.write(f"resolving {len(svgs)} SVGs to PNG thumbnails "
                              f"(batched)...")
            svg_png = self._resolve_svgs(svgs, o["sleep"])
            self.stdout.write(f"  resolved {len(svg_png)}/{len(svgs)}")

        saved, skipped, failed = 0, 0, []
        self.stdout.write(f"{len(qs)} clubs with a crest URL -> {out_dir}")

        for t in qs:
            fname = f"{t.slug}.png"
            path = out_dir / fname
            # An EMPTY crest_file means the URL was corrected and the file on disk
            # is stale, so it must be re-downloaded. Re-linking it instead kept AS
            # Roma showing a text wordmark after its crest had been fixed.
            if path.exists() and not o["force"] and t.crest_file == fname:
                skipped += 1
                continue

            # Use the pre-resolved PNG thumbnail for SVGs so the fetcher never
            # makes its own per-file API call.
            src = svg_png.get(t.image_url, t.image_url)
            img = _fetch_badge_image(src, _BADGE_FETCH_SIZE)
            time.sleep(o["sleep"])
            if img is None:
                failed.append((t.name, t.image_url))
                continue
            try:
                img.save(path, format="PNG", optimize=True)
            except Exception as e:
                failed.append((t.name, f"save failed: {e}"))
                continue
            t.crest_file = fname
            t.save(update_fields=["crest_file"])
            saved += 1
            if saved % 50 == 0:
                self.stdout.write(f"  {saved} saved...")

        total_kb = sum(f.stat().st_size for f in out_dir.glob("*.png")) // 1024
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(
            f"saved {saved}, already present {skipped}, failed {len(failed)}"))
        self.stdout.write(f"{len(list(out_dir.glob('*.png')))} files, {total_kb} KB "
                          f"({total_kb // 1024} MB)")
        for name, why in failed[:30]:
            self.stdout.write(self.style.WARNING(f"  FAILED {name} — {why[:70]}"))
        if len(failed) > 30:
            self.stdout.write(self.style.WARNING(f"  ... and {len(failed) - 30} more"))
        if saved:
            self.stdout.write(self.style.WARNING(
                "\nCommit static/crests/ and re-dump the fixture."))
