from django.conf import settings
from rest_framework import serializers


class CloudinaryImageField(serializers.ImageField):
    """
    Accepts an image upload (multipart) and returns the Cloudinary URL.

    The uploaded file is passed through to the model's CloudinaryField, which
    uploads it to Cloudinary when the instance is saved.
    """

    def to_internal_value(self, data):
        file = super().to_internal_value(data)
        max_size = getattr(settings, 'MAX_IMAGE_UPLOAD_SIZE', None)
        if max_size and file.size > max_size:
            raise serializers.ValidationError(
                f"Image too large (max {max_size // (1024 * 1024)} MB)."
            )
        return file

    def to_representation(self, value):
        if not value:
            return None
        return value.url
