"""Helpers for the generated API documentation."""


def exclude_legacy_routes(endpoints, **kwargs):
    """
    Hide the trailing-slash-less alias ``/api/locations/<pk>`` from the OpenAPI schema.

    The alias exists only so old clients keep working (see mpesa/urls.py); listing it next to the
    canonical ``/api/locations/<pk>/`` would show every location operation twice.
    """
    return [
        (path, path_regex, method, callback)
        for path, path_regex, method, callback in endpoints
        if not path.startswith('/api/locations/{') or path.endswith('/')
    ]
