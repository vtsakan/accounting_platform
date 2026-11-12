"""D01 S14 policy selected by the product owner on 10 November 2026."""
from functools import wraps
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from .membership import require_office_profile

COMMON = frozenset({"clients.read", "clients.write", "finance.read", "finance.write", "ownership.accept"})
MATRIX = {"accountant": COMMON, "owner": COMMON | {"office.settings", "staff.manage", "office.audit", "ownership.propose", "finance.reverse"}}


def require_capability(user, capability):
    profile = require_office_profile(user)
    if not isinstance(capability, str) or capability not in MATRIX.get(profile.role, ()):
        raise PermissionDenied("Δεν έχετε δικαίωμα για αυτή την ενέργεια.")
    return profile


def model_capability(model, *, write=False):
    return ("clients" if model._meta.model_name == "entity" else "finance") + (".write" if write else ".read")


def office_view(capability, *, mfa=False):
    def decorate(view):
        @login_required
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            require_capability(request.user, capability)
            return view(request, *args, **kwargs)
        wrapped.office_capability = capability
        wrapped.staff_mfa_required = mfa
        return wrapped
    return decorate


# These entry points establish identity or recipient proof before an office can
# exist. Exemptions bind both the implementation module and the route name.
IDENTITY_ROUTES = {
    "accounting.auth_views": frozenset({"login", "password-reset", "password-reset-confirm",
        "mfa-setup", "mfa-qr", "mfa-verify", "mfa-recover", "security-settings"}),
    "accounting.invite_views": frozenset({"staff-join-token", "staff-join"}),
}


def is_business_view(view, route_name):
    module = getattr(view, "__module__", "")
    # Django wraps our ModelAdmin methods while preserving their module name;
    # those callbacks use the dedicated admin/membership/permission checks.
    if module == "accounting.admin" and getattr(view, "model_admin", None) is not None:
        return False
    return (hasattr(view, "office_capability") or
        (module.startswith("accounting.") and route_name not in IDENTITY_ROUTES.get(module, ())))


def guard_business_autocomplete(request):
    """Validate the source relation, not just Django's remote-model permission.

    In particular, read-only archive metadata must never turn the shared
    endpoint into a global auth.User search. Office ownership is not editable.
    """
    from django.apps import apps
    from django.contrib import admin
    from django.core.exceptions import FieldDoesNotExist
    from django.db.models import ForeignKey
    from .office_access import MODELS
    denied = "Η επιλογή συσχετισμένης εγγραφής δεν επιτρέπεται."
    try:
        source = apps.get_model("accounting", request.GET.get("model_name", ""))
        field = source._meta.get_field(request.GET.get("field_name", ""))
        source_admin = admin.site._registry.get(source)
        remote = field.remote_field.model if isinstance(field, ForeignKey) else None
        if (source not in MODELS or remote not in MODELS or source_admin is None
                or not field.editable or field.name in source_admin.get_readonly_fields(request)
                or remote not in admin.site._registry or not source_admin.has_view_permission(request)):
            raise PermissionDenied(denied)
        require_capability(request.user, model_capability(source))
        require_capability(request.user, model_capability(remote))
    except (LookupError, FieldDoesNotExist, AttributeError, ValueError):
        raise PermissionDenied(denied) from None
    request._office_autocomplete_target = remote


class OfficeCapabilityMiddleware:
    """Fail closed for new business routes; every route needs a named capability."""
    ROUTES = {name: capability for capability, names in {
        "finance.read": ("dashboard", "transaction-list", "summary-report", "agreement-list", "agreement-detail"),
        "finance.write": ("add-expense", "add-income", "add-transfer", "add-agreement", "edit-agreement"),
        "clients.read": ("customer-list", "supplier-list", "entity-detail"),
        "clients.write": ("add-entity", "edit-entity"),
    }.items() for name in names}

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        match = getattr(request, "resolver_match", None)
        route_name = getattr(match, "url_name", None)
        if is_business_view(view_func, route_name):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            capability = getattr(view_func, "office_capability", None)
            if view_func.__module__ == "accounting.views" and capability is None:
                capability = self.ROUTES.get(route_name)
            require_capability(request.user, capability)
        if (request.user.is_authenticated and match is not None and match.namespace == "admin"
                and match.url_name == "autocomplete" and request.GET.get("app_label") == "accounting"):
            guard_business_autocomplete(request)
