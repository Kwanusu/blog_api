# blogs_api/middleware.py
import logging
import time

logger = logging.getLogger(__name__)


class RequestTimingMiddleware:
    """Measure how long each request takes and report it."""

    def __init__(self, get_response):
        # Runs ONCE when the server starts.
        self.get_response = get_response

    def __call__(self, request):
        # Runs for EVERY request.
        start_time = time.perf_counter()

        response = self.get_response(request)  # call the rest of Django

        duration_ms = (time.perf_counter() - start_time) * 1000

        logger.info(
            "method=%s path=%s status=%s duration_ms=%.2f",
            request.method,
            request.path,
            response.status_code,
            duration_ms,
        )
        response["X-Request-Duration-ms"] = f"{duration_ms:.2f}"
        return response