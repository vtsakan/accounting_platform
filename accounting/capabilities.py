"""D01 S14 policy selected by the product owner on 10 November 2026."""
from functools import wraps
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from .membership import require_office_profile

COMMON = frozenset({"clients.read", "clients.write", "finance.read", "finance.write", "ownership.accept"})
MATRIX = {"accountant": COMMON, "owner": COMMON | {"office.settings", "staff.manage", "office.audit", "ownership.propose"}}


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
        if not request.user.is_authenticated:
            return None
        if view_func.__module__ == "accounting.views":
            require_capability(request.user, self.ROUTES.get(request.resolver_match.url_name))
        elif hasattr(view_func, "office_capability"):
            require_capability(request.user, view_func.office_capability)
