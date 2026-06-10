from django.db import models


class Country(models.Model):
    name = models.CharField(max_length=255, unique=True)
    code = models.CharField(max_length=2, unique=True)  # ISO 3166-1 alpha-2
    uefa_rank = models.IntegerField(null=True, blank=True)  # 5-year country coefficient rank

    def __str__(self):
        return self.name

    class Meta:
        verbose_name_plural = "countries"


class League(models.Model):
    name = models.CharField(max_length=255)
    country = models.ForeignKey(Country, on_delete=models.CASCADE,
                                related_name="leagues", db_index=True)
    division_level = models.IntegerField()  # 1=top flight, 2=second, ...

    def __str__(self):
        return f"{self.name} ({self.country})"

    class Meta:
        ordering = ["country", "division_level"]


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

    wikipedia_url = models.URLField(max_length=500, blank=True, null=True)
    transfermarkt_url = models.URLField(max_length=500, blank=True, null=True)

    image_url = models.URLField(max_length=1000, blank=True, null=True)
    image_credit = models.TextField(blank=True, null=True)
    # Gallery: list of {"url": str, "credit": str} dicts scraped from Wikimedia Commons
    extra_images = models.JSONField(default=list, blank=True)
    description = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.name


class Team(models.Model):
    TIER_CHOICES = [
        (1, 'First Division'),
        (2, 'Second Division'),
        (3, 'Third Division'),
    ]

    GIRONE_CHOICES = [
    ("A", "Girone A"),
    ("B", "Girone B"),
    ("C", "Girone C"),
    ]



    name = models.CharField(max_length=255)
    founded = models.DateField(null=True, blank=True)
    tier = models.IntegerField(choices=TIER_CHOICES)
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


    def __str__(self):
        return self.name

class StadiumDevelopment(models.Model):
    stadium = models.ForeignKey(Stadium, on_delete=models.CASCADE, null=True, blank=True, db_index=True)

    name = models.CharField(max_length=255)

    project_type = models.CharField(
        max_length=30,
        choices=[
            ("NEW", "New Stadium"),
            ("REDEVELOPMENT", "Redevelopment"),
            ("EXPANSION", "Expansion"),
        ]
    )

    status = models.CharField(
        max_length=30,
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

    architect = models.CharField(max_length=255, blank=True, null=True)
    developer = models.CharField(max_length=255, blank=True, null=True)

    image_url = models.URLField(max_length=1000, blank=True, null=True)
    image_credit =models.TextField(blank=True, null=True)
    source_url = models.URLField(max_length=500, blank=True, null=True)


    notes = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.name
