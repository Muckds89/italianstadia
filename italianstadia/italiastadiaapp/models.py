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
    stadium = models.ForeignKey(Stadium, on_delete=models.CASCADE, related_name='teams', db_index=True)
    manager = models.CharField(max_length=255, blank=True, null=True)
    num_of_titles = models.IntegerField(null=True, blank=True)
    city = models.ForeignKey(City, on_delete=models.CASCADE, related_name='teams', db_index=True)
    average_attendance = models.IntegerField(null=True, blank=True)

    wikipedia_url = models.URLField(max_length=500, blank=True, null=True)
    transfermarkt_url = models.URLField(max_length=500, blank=True, null=True)

    image_url = models.URLField(max_length=1000, blank=True, null=True)
    image_credit = models.TextField(blank=True, null=True)
    description = models.TextField(blank=True, null=True)

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
