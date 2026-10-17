from django.db import models


# The unused `Payment` model that used to be here was removed (review item B7): nothing wrote to it and it
# shared a name with `payments.Payment`, which is the real payment table.
class Location(models.Model):
    address = models.CharField(max_length=250, help_text='Address of the location')
    latitude = models.FloatField(null=True, blank=True, help_text='Latitude of the location')
    longitude = models.FloatField(null=True, blank=True, help_text='Longitude of the location')
    town = models.CharField(max_length=100, blank=True, null=True, help_text='Town/Suburb of the location')
    county = models.CharField(max_length=100, blank=True, null=True, help_text='County of the location')
    country = models.CharField(max_length=100, blank=True, null=True, help_text='Country of the location')

    def __str__(self):
        return self.address
