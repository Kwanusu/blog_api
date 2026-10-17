"""Rate limits for the location endpoints."""
from rest_framework.throttling import UserRateThrottle


class GeocodingThrottle(UserRateThrottle):
    """
    Review fix A4: every create/update may trigger billable Google Geocoding requests, so each
    signed-in user gets a ceiling (``DEFAULT_THROTTLE_RATES['geocoding']`` in settings).
    Plain reads never call Google, so they are not counted against it.
    """

    scope = 'geocoding'

    def allow_request(self, request, view):
        if request.method in ('GET', 'HEAD', 'OPTIONS'):
            return True
        return super().allow_request(request, view)
