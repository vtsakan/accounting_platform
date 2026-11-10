# accounting/admin.py

from django.contrib import admin
from .models import Entity, CashAccount, Category, Transaction, Agreement
from django.utils.translation import gettext
from django.core.exceptions import PermissionDenied
from django.http import Http404
from .membership import require_office_profile
from .office_access import records, save_for_user
from .capabilities import require_capability, model_capability
from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import UserChangeForm
from .models import AccountantProfile


class GuardedUserChangeForm(UserChangeForm):
    def clean_is_active(self):
        active = self.cleaned_data["is_active"]
        if not active and self.instance.pk:
            profile = AccountantProfile.objects.filter(user=self.instance, user__is_active=True,
                role="owner", is_active=True, office__is_active=True).first()
            if profile and not AccountantProfile.objects.filter(office_id=profile.office_id, role="owner",
                is_active=True, user__is_active=True).exclude(user_id=self.instance.pk).exists():
                raise forms.ValidationError("Το γραφείο πρέπει να διατηρεί τουλάχιστον έναν ενεργό υπεύθυνο.")
        return active


class PlatformUserAdmin(UserAdmin):
    form = GuardedUserChangeForm


admin.site.unregister(get_user_model())
admin.site.register(get_user_model(), PlatformUserAdmin)


class OfficeRelatedFilter(admin.RelatedFieldListFilter):
    def field_choices(self, field, request, model_admin):
        profile = require_office_profile(request.user)
        return field.get_choices(include_blank=False, limit_choices_to={"office_id": profile.office_id})


class OfficeAdminMixin:
    actions = None

    def has_view_permission(self, request, obj=None):
        try:
            require_capability(request.user, model_capability(self.model))
        except PermissionDenied:
            return False
        return super().has_view_permission(request, obj)

    def has_add_permission(self, request):
        try:
            require_capability(request.user, model_capability(self.model, write=True))
        except PermissionDenied:
            return False
        return super().has_add_permission(request)

    def has_change_permission(self, request, obj=None):
        try:
            require_capability(request.user, model_capability(self.model, write=True))
        except PermissionDenied:
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return False  # Posted-record deletion awaits the explicit reversal workflows.

    def get_queryset(self, request):
        try:
            return records(self.model, request.user)
        except PermissionDenied:
            return self.model.objects.none()

    def get_object(self, request, object_id, from_field=None):
        obj = super().get_object(request, object_id, from_field)
        if obj is None:
            raise Http404("Η εγγραφή δεν βρέθηκε.")
        return obj

    def has_module_permission(self, request):
        try:
            require_office_profile(request.user)
        except PermissionDenied:
            return False
        return super().has_module_permission(request)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        kwargs['queryset'] = records(db_field.remote_field.model, request.user)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def get_form(self, request, obj=None, **kwargs):
        parent = super().get_form(request, obj, **kwargs)
        actor = request.user
        class ScopedAdminForm(parent):
            def __init__(self, *args, **options):
                super().__init__(*args, **options)
                profile = require_office_profile(actor)
                if self.instance.office_id and self.instance.office_id != profile.office_id:
                    raise PermissionDenied("Δεν έχετε πρόσβαση σε αυτή την εγγραφή.")
                self.instance.office_id = profile.office_id
        return ScopedAdminForm

    def save_model(self, request, obj, form, change):
        save_for_user(obj, request.user)

    def changelist_view(self, request, extra_context=None):
        if request.method == 'POST' and request.POST.get('action'):
            raise PermissionDenied("Η μαζική ενέργεια δεν υποστηρίζεται.")
        return super().changelist_view(request, extra_context)

    def lookup_allowed(self, lookup, value, request):
        if lookup.startswith('office'):
            return False
        return super().lookup_allowed(lookup, value, request)

admin.site.site_header = "Διαχείριση λογιστικής πλατφόρμας"
admin.site.site_title = "Λογιστική πλατφόρμα"
admin.site.index_title = "Διαχείριση"


class GreekAdminMixin:
    def formfield_for_dbfield(self, db_field, request, **kwargs):
        field = super().formfield_for_dbfield(db_field, request, **kwargs)
        if field is not None:
            field.label = gettext(str(field.label))
            if field.help_text:
                field.help_text = gettext(str(field.help_text))
            if db_field.choices:
                field.choices = [(key, gettext(str(label))) for key, label in field.choices]
        return field

# We use ModelAdmin classes to customize the admin interface

@admin.register(Entity)
class EntityAdmin(OfficeAdminMixin, GreekAdminMixin, admin.ModelAdmin):
    # Columns to display in the list view
    list_display = ('name', 'entity_type', 'vat_number', 'phone_number')
    # Fields to filter by in the right sidebar
    list_filter = ('entity_type',)
    # Fields to search by
    search_fields = ('name', 'vat_number')

@admin.register(CashAccount)
class CashAccountAdmin(OfficeAdminMixin, GreekAdminMixin, admin.ModelAdmin):
    list_display = ('name', 'opening_balance', 'is_active')
    list_filter = ('is_active',)

@admin.register(Category)
class CategoryAdmin(OfficeAdminMixin, GreekAdminMixin, admin.ModelAdmin):
    list_display = ('name', 'parent')
    list_filter = (('parent', OfficeRelatedFilter),)
    search_fields = ('name',)

@admin.register(Transaction)
class TransactionAdmin(OfficeAdminMixin, GreekAdminMixin, admin.ModelAdmin):
    list_display = ('transaction_date', 'description', 'amount', 'transaction_type', 'cash_account', 'category', 'entity')
    list_filter = ('transaction_type', ('cash_account', OfficeRelatedFilter), 'transaction_date')
    search_fields = ('description', 'entity__name')
    # Make the date have a nice hierarchy filter
    date_hierarchy = 'transaction_date'

@admin.register(Agreement)
class AgreementAdmin(OfficeAdminMixin, GreekAdminMixin, admin.ModelAdmin):
    # Columns to display in the list view
    list_display = ('entity', 'agreement_type', 'total_amount', 'status', 'start_date')
    # Fields to filter by in the right sidebar
    list_filter = ('agreement_type', 'status')
    # Fields to search by
    search_fields = ('entity__name', 'description')
    # Make the date have a nice hierarchy filter
    date_hierarchy = 'start_date'
