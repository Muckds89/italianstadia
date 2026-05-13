from django.db import models


class City(models.Model):
    name = models.CharField(max_length=100)
    population = models.IntegerField()
    country = models.CharField(max_length=100)
    wikipedia_url = models.URLField(blank=True, null=True)

    image_url = models.URLField(blank=True, null=True)
    image_credit = models.CharField(max_length=255, blank=True, null=True)
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
    name = models.CharField(max_length=100)
    capacity = models.IntegerField(null=True, blank=True)
    address = models.CharField(max_length=255, blank=True, null=True)
    year_of_construction = models.IntegerField(null=True, blank=True)
    city = models.ForeignKey(City, on_delete=models.CASCADE, related_name='stadiums')
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)

    owner_raw = models.TextField(blank=True, null=True)
    ownership = models.CharField(
        max_length=20,
        choices=OWNERSHIP_CHOICES,
        default="UNKNOWN"
    )

    wikipedia_url = models.URLField(blank=True, null=True)
    transfermarkt_url = models.URLField(blank=True, null=True)

    image_url = models.URLField(blank=True, null=True)
    image_credit = models.CharField(max_length=255, blank=True, null=True)
    description = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.name


class Team(models.Model):
    TIER_CHOICES = [
        (1, 'Serie A'),
        (2, 'Serie B'),
        (3, 'Serie C')    ]

    GIRONE_CHOICES = [
    ("A", "Girone A"),
    ("B", "Girone B"),
    ("C", "Girone C"),
    ]



    name = models.CharField(max_length=100)
    founded = models.DateField(null=True, blank=True)
    tier = models.IntegerField(choices=TIER_CHOICES)
    girone = models.CharField(
    max_length=1,
    choices=GIRONE_CHOICES,
    blank=True,
    null=True
    )
    stadium = models.ForeignKey(Stadium, on_delete=models.CASCADE, related_name='teams')
    manager = models.CharField(max_length=100, blank=True, null=True)
    num_of_titles = models.IntegerField(default=0)
    city = models.ForeignKey(City, on_delete=models.CASCADE, related_name='teams')
    average_attendance = models.FloatField(null=True, blank=True)

    wikipedia_url = models.URLField(blank=True, null=True)
    transfermarkt_url = models.URLField(blank=True, null=True)

    image_url = models.URLField(blank=True, null=True)
    image_credit = models.CharField(max_length=255, blank=True, null=True)
    description = models.TextField(blank=True, null=True)

    under_development_stadium = models.ForeignKey(
    'StadiumDevelopment',
    on_delete=models.SET_NULL,
    null=True,
    blank=True,
    related_name='future_tenants'
    )


    def __str__(self):
        return self.name

class StadiumDevelopment(models.Model):
    stadium = models.ForeignKey(Stadium, on_delete=models.CASCADE, null=True, blank=True)

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

    latitude = models.FloatField()
    longitude = models.FloatField()

    architect = models.CharField(max_length=255, blank=True)
    developer = models.CharField(max_length=255, blank=True)

    image_url = models.URLField(blank=True, null=True)
    image_credit = models.CharField(max_length=255, blank=True, null=True)
    source_url = models.URLField(blank=True)


    notes = models.TextField(blank=True)

    def __str__(self):
        return self.name
