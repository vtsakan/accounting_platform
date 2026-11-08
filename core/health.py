"""Machine health responses contain no identity, configuration or client data."""

from django.db import DatabaseError, connection
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe


@never_cache
@require_safe
def live(request):
    request.get_host()  # Validate even though health doesn't otherwise need it.
    return JsonResponse({"status": "ok"})


@never_cache
@require_safe
def ready(request):
    request.get_host()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            if cursor.fetchone() != (1,):
                return JsonResponse({"status": "unavailable"}, status=503)
    except DatabaseError:
        connection.close_if_unusable_or_obsolete()
        return JsonResponse({"status": "unavailable"}, status=503)
    return JsonResponse({"status": "ready"})
