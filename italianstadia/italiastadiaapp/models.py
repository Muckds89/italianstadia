import uuid as _uuid

from django.db import models
from django.utils.text import slugify


class Country(models.Model):
    name = models.CharField(max_length=255, unique=True)
    code = models.CharField(max_length=2, unique=True)  # ISO 3166-1 alpha-2
    uefa_rank = models.IntegerField(null=True, blank=True)  # 5-year country coefficient rank
    population = models.IntegerField(null=True, blank=True)  # for stadium-density insight

    def __str__(self):
        return self.name

    class Meta:
        verbose_name_plural = "countries"


class League(models.Model):
    name = models.CharField(max_length=255, db_index=True)
    country = models.ForeignKey(Country, on_delete=models.CASCADE,
                                related_name="leagues", db_index=True)
    division_level = models.IntegerField()  # 1=top flight, 2=second, ...
    # Which season this league's team/attendance data reflects ("2025/26").
    # Leagues are re-scraped one by one as their new season kicks off; the old
    # season's data stays live (and correctly labelled) until then.
    season = models.CharField(max_length=9, blank=True, default="2025/26")
    # Hide a league from site-facing lists and filters while our coverage of it is
    # incomplete. Set on second tiers that exist only to hold relegated clubs — a
    # visitor seeing "Scottish Championship: 1 club" would read it as the whole
    # division. The clubs and their stadiums stay visible; only the league listing
    # is suppressed. Clear this once the division is fully scraped.
    hidden = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.name} ({self.country})"

    class Meta:
        ordering = ["country", "division_level"]
        unique_together = [("name", "country")]


class City(models.Model):
    name = models.CharField(max_length=255)
    population = models.IntegerField(null=True, blank=True)
    country = models.CharField(max_length=255, db_index=True)
    wikipedia_url = models.URLField(max_length=500, blank=True, null=True)

    image_url = models.URLField(max_length=1000, blank=True, null=True)  
    image_credit = models.TextField(blank=True, null=True)
    description = models.TextField(blank=True, null=True)


    def __str__(self):
        return self.name


class Stadium(models.Model):
    OWNERSHIP_CHOICES = [
        ("PUBLIC", "Public"),
        ("PRIVATE", "Private"),
        ("MIXED", "Mixed"),
        ("UNKNOWN", "Unknown"),
    ]
    name = models.CharField(max_length=255)
    capacity = models.IntegerField(null=True, blank=True)
    address = models.CharField(max_length=500, blank=True, null=True)
    year_of_construction = models.IntegerField(null=True, blank=True)
    city = models.ForeignKey(City, on_delete=models.CASCADE, related_name='stadiums', db_index=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    owner_raw = models.TextField(blank=True, null=True)
    ownership = models.CharField(
        max_length=20,
        choices=OWNERSHIP_CHOICES,
        default="UNKNOWN"
    )

    slug = models.SlugField(max_length=255, unique=True, blank=True)

    stadium_type = models.CharField(
        max_length=30, null=True, blank=True,
        choices=[
            ("OPEN", "Open"),
            ("CLOSED", "Closed"),
            ("RETRACTABLE", "Retractable roof"),
            ("INDOOR", "Indoor"),
        ],
    )
    surface = models.CharField(
        max_length=20, null=True, blank=True,
        choices=[
            ("GRASS", "Grass"),
            ("ARTIFICIAL", "Artificial"),
            ("HYBRID", "Hybrid"),
        ],
    )
    architect = models.CharField(max_length=255, null=True, blank=True)
    # List of {tournament, year, status["CONFIRMED"|"CANDIDATE"], matches}
    tournaments = models.JSONField(default=list, blank=True)

    wikipedia_url = models.URLField(max_length=500, blank=True, null=True)
    transfermarkt_url = models.URLField(max_length=500, blank=True, null=True)

    image_url = models.URLField(max_length=1000, blank=True, null=True)
    image_credit = models.TextField(blank=True, null=True)
    # Gallery: list of {"url": str, "credit": str} dicts scraped from Wikimedia Commons
    extra_images = models.JSONField(default=list, blank=True)
    description = models.TextField(blank=True, null=True)

    # When True, the Transfermarkt/Wikipedia scraper will NOT overwrite this
    # stadium — it preserves manual corrections across the weekly auto-scrape.
    locked = models.BooleanField(
        default=False,
        help_text="Protect manual corrections — the scraper skips locked stadiums.",
    )

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name) or f"stadium-{self.pk or 0}"
            slug = base
            n = 2
            while Stadium.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base}-{n}"
                n += 1
            self.slug = slug
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Team(models.Model):
    TIER_CHOICES = [
        (1, 'First Division'),
        (2, 'Second Division'),
        (3, 'Third Division'),
        # Fourth tier: reached whenever a covered third tier relegates a club we
        # already hold (England's League Two, Germany's Regionalliga). Those rows
        # existed with tier=4 before it was a declared choice -- `choices` is not a
        # database constraint, so they saved fine and only full_clean() would have
        # objected. Declared here so the value is legitimate rather than incidental.
        (4, 'Fourth Division'),
    ]

    is_national = models.BooleanField(default=False, db_index=True)

    GIRONE_CHOICES = [
    ("A", "Girone A"),
    ("B", "Girone B"),
    ("C", "Girone C"),
    ]



    name = models.CharField(max_length=255)
    founded = models.DateField(null=True, blank=True)
    tier = models.IntegerField(choices=TIER_CHOICES, null=True, blank=True)
    girone = models.CharField(
    max_length=1,
    choices=GIRONE_CHOICES,
    blank=True,
    null=True
    )
    # Nullable: several national teams have NO home ground. Portugal rotate between
    # the Luz, Alvalade and the Dragao; asserting any one of them as "their stadium"
    # publishes a fact that isn't true. A club always has a ground, so in practice
    # this is null only for rotating national sides.
    stadium = models.ForeignKey(Stadium, on_delete=models.CASCADE, related_name='teams',
                                db_index=True, null=True, blank=True)
    manager = models.CharField(max_length=255, blank=True, null=True)
    num_of_titles = models.IntegerField(null=True, blank=True)
    city = models.ForeignKey(City, on_delete=models.CASCADE, related_name='teams', db_index=True)
    average_attendance = models.IntegerField(null=True, blank=True)

    wikipedia_url = models.URLField(max_length=500, blank=True, null=True)
    transfermarkt_url = models.URLField(max_length=500, blank=True, null=True)

    image_url = models.URLField(max_length=1000, blank=True, null=True)
    image_credit = models.TextField(blank=True, null=True)
    description = models.TextField(blank=True, null=True)

    # Filename (not a path) under static/crests/ of the locally stored crest.
    # Map exports used to fetch every crest from a third party at render time;
    # Transfermarkt then soft-blocked us and Wikimedia throttled the replacement,
    # both of which silently turned badges into bare dots on published maps. The
    # renderer prefers this file and falls back to image_url, which is kept so the
    # provenance survives and download_crests can re-run.
    crest_file = models.CharField(max_length=255, blank=True, default="")

    locked = models.BooleanField(
        default=False,
        help_text="Protect manual corrections — the scraper skips locked teams.",
    )

    league = models.ForeignKey(
        "League",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="teams",
        db_index=True,
    )

    under_development_stadium = models.ForeignKey(
    'StadiumDevelopment',
    on_delete=models.SET_NULL,
    null=True,
    blank=True,
    related_name='future_tenants',
    db_index=True,
    )

    uefa_coefficient = models.FloatField(null=True, blank=True)

    # Which UEFA club competition this club is in THIS season, for continental maps.
    # Blank (not null) means "not in Europe", matching how every other optional
    # CharField on this model reads, so a filter never has to test for both.
    #
    # This records the LEAGUE PHASE only — the 36 clubs each competition draws after
    # qualifying — not the qualifying rounds, where a club can be knocked out of one
    # competition into another and the answer changes week to week. Set it once the
    # league phase draw is known.
    EUROPEAN_COMPETITION_CHOICES = [
        ("UCL",  "UEFA Champions League"),
        ("UEL",  "UEFA Europa League"),
        ("UECL", "UEFA Conference League"),
    ]
    european_competition = models.CharField(
        max_length=8, choices=EUROPEAN_COMPETITION_CHOICES,
        blank=True, default="", db_index=True)

    # Where this club hosts its EUROPEAN home matches, when that is not `stadium`.
    #
    # A club's domestic ground and its European ground are two different facts, and
    # a continental map that publishes the first is wrong even though the club plays
    # there every other week. Two readers caught this on the same map: AGF Aarhus are
    # in a temporary ground while their new stadium is built and it is not licensed
    # for European matches, so they host at Cepheus Park Randers; Mjallby AIF host at
    # Olympia in Helsingborg, 147km from Strandvallen, for the same reason.
    #
    # Null is the normal case and means "the same ground as always" -- this is NOT a
    # second home ground field, and nothing outside the UEFA export path reads it.
    # The replacement is frequently in another CITY, and for clubs barred from hosting
    # at home it is in another COUNTRY, so the marker moves; the club's federation,
    # which drives country highlighting, stays its own.
    uefa_stadium = models.ForeignKey(
        Stadium, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="uefa_tenants", db_index=True,
        help_text="Ground used for European home matches, if not the usual one.")

    slug = models.SlugField(max_length=255, unique=True, blank=True)

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name) or f"team-{self.pk or 0}"
            slug = base
            n = 2
            while Team.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base}-{n}"
                n += 1
            self.slug = slug
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

class StadiumDevelopment(models.Model):
    stadium = models.ForeignKey(Stadium, on_delete=models.CASCADE, null=True, blank=True, db_index=True)

    name = models.CharField(max_length=255)

    slug = models.SlugField(max_length=255, unique=True, blank=True)

    project_type = models.CharField(
        max_length=30, blank=True,
        choices=[
            ("NEW", "New Stadium"),
            ("REDEVELOPMENT", "Redevelopment"),
            ("EXPANSION", "Expansion"),
        ]
    )

    status = models.CharField(
        max_length=30, blank=True,
        choices=[
            ("PLANNING", "Planning"),
            ("APPROVED", "Approved"),
            ("UNDER_CONSTRUCTION", "Under Construction"),
            ("ON_HOLD", "On Hold"),
            ("COMPLETED", "Completed"),
        ]
    )

    future_capacity = models.IntegerField(null=True, blank=True)

    estimated_opening = models.IntegerField(null=True, blank=True)

    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    country = models.CharField(max_length=255, null=True, blank=True)

    architect = models.CharField(max_length=255, blank=True, null=True)
    developer = models.CharField(max_length=255, blank=True, null=True)

    image_url = models.URLField(max_length=1000, blank=True, null=True)
    image_credit =models.TextField(blank=True, null=True)
    extra_images = models.JSONField(default=list, blank=True)  # gallery: [{url, credit}]
    source_url = models.URLField(max_length=500, blank=True, null=True)
    instagram_url = models.URLField(max_length=500, blank=True, null=True)  # architect IG post to embed


    notes = models.TextField(blank=True, null=True)
    tournaments = models.JSONField(default=list, blank=True)

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name) or f"development-{self.pk or 0}"
            slug = base
            n = 2
            while StadiumDevelopment.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base}-{n}"
                n += 1
            self.slug = slug
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class LastRefresh(models.Model):
    """Single-row table (pk=1) tracking the last automated season refresh run."""
    ran_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=[("SUCCESS", "Success"), ("FAILED", "Failed")],
        blank=True,
    )
    detail = models.TextField(blank=True)

    class Meta:
        verbose_name = "Last Refresh"
        verbose_name_plural = "Last Refresh"

    def __str__(self):
        return f"{self.status} @ {self.ran_at}" if self.ran_at else "Never run"


class ExportToken(models.Model):
    """One-time download token created after a successful Stripe payment."""
    token           = models.UUIDField(default=_uuid.uuid4, unique=True, db_index=True)
    stripe_session  = models.CharField(max_length=255, db_index=True)
    filters_json    = models.TextField()          # JSON-encoded export params
    paid            = models.BooleanField(default=False)
    used            = models.BooleanField(default=False)
    created_at      = models.DateTimeField(auto_now_add=True)
    expires_at      = models.DateTimeField()      # set to created_at + 24h

    def __str__(self):
        return f"ExportToken {self.token} paid={self.paid} used={self.used}"
