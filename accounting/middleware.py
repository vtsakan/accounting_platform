"""Fresh staff office context for the S12 record-scoped application/admin."""

from django.core.exceptions import PermissionDenied
from django.shortcuts import render
from django.utils.deprecation import MiddlewareMixin

from .membership import require_office_profile
from .capabilities import is_business_view


class ActiveOfficeMiddleware(MiddlewareMixin):
    def process_response(self, request, response):
        if getattr(request, "_office_private_response", False) or hasattr(request, "accountant_profile"):
            response["Cache-Control"] = "no-store, private"
        return response

    def process_view(self, request, view_func, view_args, view_kwargs):
        model_admin = getattr(view_func, "model_admin", None)
        match = getattr(request, "resolver_match", None)
        business_view = is_business_view(view_func, getattr(match, 'url_name', None))
        business_admin = model_admin is not None and model_admin.model._meta.app_label == "accounting"
        # Django's shared autocomplete endpoint is not bound to a ModelAdmin.
        # Its app label determines sensitivity, never the caller's office.
        generic_admin = match is not None and match.namespace == "admin" and (
            (match.url_name == "autocomplete" and request.GET.get("app_label") == "accounting")
            or (match.url_name == "app_list" and view_kwargs.get("app_label") == "accounting"))
        request._office_private_response = business_view or business_admin or generic_admin
        if not request._office_private_response or not request.user.is_authenticated:
            return None  # Existing auth views enforce anonymous login/redirects.
        try:
            profile = require_office_profile(request.user)
        except PermissionDenied:
            response = render(request, "accounting/office_access_denied.html", status=403)
            response["Cache-Control"] = "no-store, private"
            return response
        request.accountant_profile = profile
        request.office = profile.office
        return None
