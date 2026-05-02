from django.db import models

class City(models.Model):
    name = models.CharField(max_length=100)
    population = models.IntegerField()
    country = models.CharField(max_length=100)

    def __str__(self):
        return self.name

class Stadium(models.Model):
    name = models.CharField(max_length=100)
    capacity = models.IntegerField()
    address = models.CharField(max_length=255)
    year_of_construction = models.IntegerField()
    city = models.ForeignKey(City, on_delete=models.CASCADE, related_name='stadiums')
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)

    def __str__(self):
        return self.name

class Team(models.Model):
    TIER_CHOICES = [
        (1, 'Serie A'),
        (2, 'Serie B'),
        (3, 'Serie C'),
        (4, 'Serie D'),
    ]

    name = models.CharField(max_length=100)
    founded = models.DateField()
    tier = models.IntegerField(choices=TIER_CHOICES)
    stadium = models.ForeignKey(Stadium, on_delete=models.CASCADE, related_name='teams')
    manager = models.CharField(max_length=100, blank=True, null=True)
    num_of_titles = models.IntegerField(default=0)
    city = models.ForeignKey(City, on_delete=models.CASCADE, related_name='teams')
    average_attendance = models.FloatField(null=True, blank=True)  # Moved from Stadium to Team


    def __str__(self):
        return self.name
