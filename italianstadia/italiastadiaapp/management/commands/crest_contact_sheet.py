"""
crest_contact_sheet
===================
Render the badges we ship as a labelled grid, so they can be CHECKED BY LOOKING
at them. With ``--compare`` it puts the shipped badge next to the one the club's
own Wikipedia infobox names, which is the only way to settle an `audit_crests`
MISMATCH: two filenames tell you nothing about whether they are the same image.

CLAUDE.md has said "render a contact sheet and inspect it" since Marseille's
stale badge and FC Kharkiv's pre-rebrand "M" were found that way -- but no such
command existed, so every inspection was hand-rolled and most were skipped. A
filename check is not a look.

    # every badge on the continental maps, as a grid
    python -X utf8 manage.py crest_contact_sheet --uefa -o sheets/uefa

    # shipped vs infobox, only the rows an audit flagged
    python -X utf8 manage.py audit_crests --uefa --json audit.json
    python -X utf8 manage.py crest_contact_sheet --compare audit.json -o sheets/flagged

Writes `<out>_1.png`, `<out>_2.png`, ... -- one sheet per page, because a single
image of 1,000 badges is unreadable at any size a viewer will render.
"""
import io
import json
import os
import time
import urllib.parse

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from PIL import Image, ImageDraw, ImageFont

from italiastadiaapp.models import Team
from italiastadiaapp.management.commands.refresh_dead_crests import chunks

UA = {"User-Agent": "stadiamap/1.0 (destavola.marco@gmail.com)"}

TILE = 132          # badge box, px
PAD = 12
LABEL_H = 34
COLS_GRID = 8
COLS_CMP = 4        # a comparison cell is two badges wide
ROWS = 8

BG = (250, 250, 250)
INK = (20, 20, 20)
MUTED = (110, 110, 110)
FLAG = (200, 40, 40)


def _font(size, bold=False):
    for name in (("DejaVuSans-Bold.ttf", "arialbd.ttf") if bold
                 else ("DejaVuSans.ttf", "arial.ttf")):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _fit(im, box):
    """Letterbox onto a transparent square without distorting the badge."""
    im = im.convert("RGBA")
    im.thumbnail((box, box), Image.LANCZOS)
    canvas = Image.new("RGBA", (box, box), (0, 0, 0, 0))
    canvas.paste(im, ((box - im.width) // 2, (box - im.height) // 2), im)
    return canvas


def _ellipsis(draw, text, font, width):
    if draw.textlength(text, font=font) <= width:
        return text
    while text and draw.textlength(text + "...", font=font) > width:
        text = text[:-1]
    return text + "..."


class Command(BaseCommand):
    help = "Render club crests as labelled contact sheets for visual checking."

    def add_arguments(self, p):
        p.add_argument("-o", "--out", required=True,
                       help="output path prefix; _1.png, _2.png are appended")
        p.add_argument("--compare", help="an audit_crests --json file")
        p.add_argument("--verdicts", default="HISTORIC,MISMATCH,NO-CREST",
                       help="with --compare, which verdicts to include")
        p.add_argument("--uefa", action="store_true")
        p.add_argument("--league")
        p.add_argument("--country")
        p.add_argument("--split", action="store_true",
                       help="with --compare, write ONE image per club "
                            "(<out>/<team id>.png) instead of paged sheets, so a "
                            "reviewer can be pointed at exactly one comparison")

    # -- remote files -------------------------------------------------------
    @staticmethod
    def _key(name):
        """MediaWiki normalises `_` to ` ` in the titles it echoes back.

        Infobox parameters are written both ways ("Atalanta_BC_new_logo.svg",
        "KAA Gent logo.svg"), so keying the resolved URLs by the returned title
        loses every underscored name -- 76 of 146 files came back "not
        available" purely because of this, which reads as "Wikipedia has no such
        file" rather than "we looked it up under the wrong key".
        """
        return (name or "").replace("_", " ").strip()

    def _file_urls(self, names, width=256):
        """'KAA Gent logo.svg' -> a rasterised URL at `width` px.

        `iiurlwidth` is what makes an SVG usable here: MediaWiki rasterises it
        server-side, so PIL never has to render vector art it cannot read.
        """
        out = {}
        for batch in chunks(sorted({self._key(n) for n in names}), 40):
            try:
                r = requests.get(
                    "https://en.wikipedia.org/w/api.php",
                    params={"action": "query", "format": "json",
                            "formatversion": "2", "prop": "imageinfo",
                            "iiprop": "url", "iiurlwidth": width,
                            "titles": "|".join(f"File:{n}" for n in batch)},
                    headers=UA, timeout=45)
                pages = r.json().get("query", {}).get("pages", [])
            except Exception as e:                               # noqa: BLE001
                self.stderr.write(f"  imageinfo batch failed: {e}")
                continue
            for pg in pages:
                info = (pg.get("imageinfo") or [{}])[0]
                url = info.get("thumburl") or info.get("url")
                if url:
                    out[self._key(pg["title"].split(":", 1)[-1])] = url
        return out

    def _load(self, url, tries=4):
        """Fetch one badge, with backoff.

        Wikimedia throttles bursts -- CLAUDE.md records this as the reason the
        crest downloader had to be rewritten. Fetching 150 comparison images in
        a tight loop drew 429s that arrived here as "image not available", i.e.
        a rate limit disguised as a missing file, on 72 of 146 clubs. Every one
        of them loaded fine when retried on its own.
        """
        delay = 0.6
        for attempt in range(tries):
            try:
                r = requests.get(url, headers=UA, timeout=45)
                if r.status_code == 200:
                    return Image.open(io.BytesIO(r.content))
                if r.status_code in (429, 503) and attempt < tries - 1:
                    time.sleep(delay)
                    delay *= 2
                    continue
                return None
            except Exception:                                    # noqa: BLE001
                if attempt == tries - 1:
                    return None
                time.sleep(delay)
                delay *= 2
        return None

    def _local(self, fname):
        for base in ("italiastadiaapp/static/crests", "static/crests"):
            p = os.path.join(settings.BASE_DIR, base, fname or "")
            if fname and os.path.isfile(p):
                try:
                    return Image.open(p)
                except Exception:                                # noqa: BLE001
                    return None
        return None

    # -- drawing ------------------------------------------------------------
    def _sheet(self, cells, cols, cell_w, cell_h, title):
        W = PAD + cols * (cell_w + PAD)
        rows = (len(cells) + cols - 1) // cols
        H = PAD + 30 + rows * (cell_h + PAD)
        img = Image.new("RGB", (W, H), BG)
        d = ImageDraw.Draw(img)
        d.text((PAD, PAD), title, fill=INK, font=_font(18, bold=True))
        for i, cell in enumerate(cells):
            x = PAD + (i % cols) * (cell_w + PAD)
            y = PAD + 30 + (i // cols) * (cell_h + PAD)
            cell(img, d, x, y)
        return img

    def _write(self, sheets, out):
        os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
        paths = []
        for i, im in enumerate(sheets, 1):
            p = f"{out}_{i}.png"
            im.save(p)
            paths.append(p)
            self.stdout.write(f"  wrote {p}  ({im.width}x{im.height})")
        return paths

    def handle(self, *a, **o):
        if o["compare"]:
            self._compare(o)
        else:
            self._grid(o)

    # -- mode: plain grid of what we ship -----------------------------------
    def _grid(self, o):
        qs = Team.objects.filter(is_national=False).select_related(
            "league__country").order_by("league__country__name", "name")
        if o["uefa"]:
            qs = qs.exclude(european_competition="")
        if o["league"]:
            qs = qs.filter(league__name=o["league"])
        if o["country"]:
            qs = qs.filter(league__country__name=o["country"])
        teams = list(qs)
        if not teams:
            raise CommandError("no clubs matched")

        cell_w, cell_h = TILE, TILE + LABEL_H
        f = _font(12)
        sheets = []
        per = COLS_GRID * ROWS
        for pageno, page in enumerate(chunks(teams, per), 1):
            cells = []
            for t in page:
                im = self._local(t.crest_file)
                badge = _fit(im, TILE - 8) if im else None
                name = t.name
                tag = t.european_competition or ""

                def draw(img, d, x, y, badge=badge, name=name, tag=tag):
                    d.rectangle([x, y, x + cell_w, y + cell_h],
                                outline=(225, 225, 225))
                    if badge:
                        img.paste(badge, (x + 4, y + 4), badge)
                    else:
                        d.text((x + 8, y + TILE // 2), "NO CREST",
                               fill=FLAG, font=_font(13, bold=True))
                    d.text((x + 4, y + TILE + 2),
                           _ellipsis(d, name, f, cell_w - 8), fill=INK, font=f)
                    if tag:
                        d.text((x + 4, y + TILE + 16), tag, fill=MUTED, font=f)
                cells.append(draw)
            sheets.append(self._sheet(
                cells, COLS_GRID, cell_w, cell_h,
                f"Shipped crests - sheet {pageno} "
                f"({len(page)} of {len(teams)} clubs)"))
        self._write(sheets, o["out"])

    # -- mode: shipped vs infobox -------------------------------------------
    def _compare(self, o):
        with open(o["compare"], encoding="utf-8") as fh:
            rows = json.load(fh)
        want = {v.strip().upper() for v in o["verdicts"].split(",") if v.strip()}
        rows = [r for r in rows if r["verdict"] in want]
        if not rows:
            raise CommandError(f"no rows with verdict in {sorted(want)}")
        self.stdout.write(f"comparing {len(rows)} flagged club(s)")

        urls = self._file_urls([r["infobox_file"] for r in rows
                                if r.get("infobox_file")])
        self.stdout.write(f"  resolved {len(urls)} infobox file(s)")

        if o["split"]:
            return self._compare_split(rows, urls, o["out"])

        cell_w = TILE * 2 + 12
        cell_h = TILE + LABEL_H + 16
        f = _font(12)
        fb = _font(13, bold=True)
        sheets = []
        per = COLS_CMP * ROWS
        for pageno, page in enumerate(chunks(rows, per), 1):
            cells = []
            for r in page:
                mine = self._local(r["shipped_file"])
                theirs = None
                u = urls.get(self._key(r.get("infobox_file") or ""))
                if u:
                    theirs = self._load(u)
                a = _fit(mine, TILE - 8) if mine else None
                b = _fit(theirs, TILE - 8) if theirs else None
                label = f"{r['club']}  [{r['verdict']}]"
                sub = f"{r.get('uefa') or r.get('country') or ''}"

                def draw(img, d, x, y, a=a, b=b, label=label, sub=sub):
                    d.rectangle([x, y, x + cell_w, y + cell_h],
                                outline=(225, 225, 225))
                    if a:
                        img.paste(a, (x + 4, y + 4), a)
                    if b:
                        img.paste(b, (x + TILE + 8, y + 4), b)
                    d.line([x + TILE + 4, y + 4, x + TILE + 4, y + TILE],
                           fill=(215, 215, 215))
                    d.text((x + 6, y + TILE + 2), "SHIPPED", fill=FLAG, font=f)
                    d.text((x + TILE + 10, y + TILE + 2), "INFOBOX",
                           fill=(30, 120, 40), font=f)
                    d.text((x + 4, y + TILE + 16),
                           _ellipsis(d, label, fb, cell_w - 8), fill=INK, font=fb)
                    d.text((x + 4, y + TILE + 32),
                           _ellipsis(d, sub, f, cell_w - 8), fill=MUTED, font=f)
                cells.append(draw)
            sheets.append(self._sheet(
                cells, COLS_CMP, cell_w, cell_h,
                f"SHIPPED (left, red) vs INFOBOX (right, green) - "
                f"sheet {pageno}"))
        self._write(sheets, o["out"])

    def _compare_split(self, rows, urls, out):
        """One comparison image per club, at a size worth looking at.

        A paged sheet is efficient for a person scanning for the obvious wrong
        one, but useless for pointing a specific reviewer at a specific club.
        These are named by team id so a report can cite the exact image behind
        each verdict.
        """
        os.makedirs(out, exist_ok=True)
        big = 300
        f, fb = _font(15), _font(17, bold=True)
        made, missing = 0, []
        for r in rows:
            mine = self._local(r["shipped_file"])
            u = urls.get(self._key(r.get("infobox_file") or ""))
            theirs = self._load(u) if u else None
            time.sleep(0.25)
            if theirs is None and r.get("infobox_file"):
                missing.append(r["club"])
            W, H = big * 2 + 36, big + 92
            img = Image.new("RGB", (W, H), BG)
            d = ImageDraw.Draw(img)
            for i, (im, tag, col) in enumerate(
                    ((mine, "SHIPPED (what the map draws)", FLAG),
                     (theirs, "INFOBOX (what the article shows)", (30, 120, 40)))):
                x = 12 + i * (big + 12)
                d.rectangle([x, 12, x + big, 12 + big], outline=(220, 220, 220))
                if im:
                    b = _fit(im, big - 16)
                    img.paste(b, (x + 8, 20), b)
                else:
                    d.text((x + 14, 12 + big // 2), "not available",
                           fill=MUTED, font=f)
                d.text((x, 18 + big), tag, fill=col, font=f)
            d.text((12, 42 + big), f"{r['club']}  [{r['verdict']}]",
                   fill=INK, font=fb)
            d.text((12, 64 + big),
                   f"shipped={r['shipped_file'] or '-'}   "
                   f"infobox={r.get('infobox_file') or '-'}",
                   fill=MUTED, font=f)
            img.save(os.path.join(out, f"{r['id']}.png"))
            made += 1
        self.stdout.write(f"  wrote {made} image(s) to {out}")
        if missing:
            self.stdout.write(self.style.WARNING(
                f"  {len(missing)} infobox file(s) would not load "
                f"(shown as 'not available'): {', '.join(missing[:12])}"
                + (" ..." if len(missing) > 12 else "")))
