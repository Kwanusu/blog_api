"""A geocoded address that any model can mix in, plus the matching serializer plumbing."""
from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from rest_framework import serializers


class LocationMixin(models.Model):
    address = models.CharField(max_length=255, blank=True)
    latitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True,
        validators=[MinValueValidator(Decimal('-90')), MaxValueValidator(Decimal('90'))],
    )
    longitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True,
        validators=[MinValueValidator(Decimal('-180')), MaxValueValidator(Decimal('180'))],
    )
    place_id = models.CharField(max_length=255, blank=True)

    class Meta:
        abstract = True

    @property
    def has_location(self):
        return self.latitude is not None and self.longitude is not None


LOCATION_FIELDS = ['address', 'latitude', 'longitude', 'place_id']


class LocationSerializerMixin:
    """latitude and longitude must come as a pair (a pin needs both)."""

    def validate(self, attrs):
        attrs = super().validate(attrs)
        instance = getattr(self, 'instance', None)
        lat = attrs.get('latitude', getattr(instance, 'latitude', None) if instance else None)
        lng = attrs.get('longitude', getattr(instance, 'longitude', None) if instance else None)
        if (lat is None) != (lng is None):
            raise serializers.ValidationError('Latitude and longitude must be provided together.')
        return attrs
