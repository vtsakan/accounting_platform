"""Explicit, uncached same-origin access; GSIS receives no app-side login POST."""
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from django.views.decorators.http import require_POST

from .capabilities import office_view
from .gsis_services import credentials_for_gsis


@office_view('clients.credentials', mfa=True)
@never_cache
@sensitive_post_parameters('__ALL__')
@sensitive_variables('__ALL__')
@require_POST
def credentials(request, pk, subject):
    try:
        username, password = credentials_for_gsis(request.user, pk, subject)
    except ValidationError:
        response = JsonResponse({'error': 'Δεν ήταν δυνατή η εμφάνιση των κωδικών. Ελέγξτε την καρτέλα και την πρόσβασή σας.'}, status=409)
    else:
        response = JsonResponse({'entity_id': pk, 'subject': subject,
            'username': username, 'password': password, 'stored': bool(username and password)})
    response['Cache-Control'] = 'no-store, private'
    response['Pragma'] = 'no-cache'
    response['Referrer-Policy'] = 'no-referrer'
    response['X-Content-Type-Options'] = 'nosniff'
    return response
