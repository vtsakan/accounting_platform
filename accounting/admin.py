# accounting/admin.py

from django.contrib import admin, messages
from .models import Entity, CashAccount, Category, Transaction, Agreement
from django.utils.translation import gettext
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404, HttpResponseRedirect
from .membership import require_office_profile
from .office_access import records, save_for_user
from .capabilities import require_capability, model_capability
from django import forms
from django.db.models import Q
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import UserChangeForm
from .models import AccountantProfile
from .forms import EntityForm
from core.locale import GreekMoneyField


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
            queryset = records(self.model, request.user)
            if getattr(request, '_office_autocomplete_target', None) is self.model:
                if self.model is Entity:
                    queryset = queryset.filter(is_archived=False)
                elif self.model is Agreement:
                    queryset = queryset.filter(entity__is_archived=False)
                elif self.model is CashAccount:
                    queryset = queryset.filter(is_active=True,opening_date__isnull=False)
                elif self.model is Category:
                    queryset = queryset.filter(is_active=True)
            return queryset
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
        remote = db_field.remote_field.model
        queryset = records(remote, request.user)
        if remote is Entity:
            queryset = queryset.filter(is_archived=False)
        elif remote is Agreement:
            queryset = queryset.filter(entity__is_archived=False)
        elif remote is CashAccount:
            queryset = queryset.filter(is_active=True,opening_date__isnull=False)
        elif remote is Category:
            queryset = queryset.filter(is_active=True)
        kwargs['queryset'] = queryset
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def get_form(self, request, obj=None, **kwargs):
        parent = super().get_form(request, obj, **kwargs)
        actor = request.user
        class ScopedAdminForm(parent):
            def __init__(self, *args, **options):
                if isinstance(self, EntityForm):
                    options['user'] = actor
                super().__init__(*args, **options)
                profile = require_office_profile(actor)
                if self.instance.office_id and self.instance.office_id != profile.office_id:
                    raise PermissionDenied("Δεν έχετε πρόσβαση σε αυτή την εγγραφή.")
                self.instance.office_id = profile.office_id
                # Historical links stay editable without reopening archived
                # identities for new work. Only the stored link is restored.
                if self.instance.pk:
                    for name, field in self.fields.items():
                        if isinstance(field, forms.ModelChoiceField):
                            old_key = getattr(self.instance, name + '_id', None)
                            if old_key is not None and field.queryset.model in (Entity, Agreement, CashAccount, Category):
                                allowed = records(field.queryset.model, actor)
                                field.queryset = allowed.filter(Q(pk__in=field.queryset.values('pk')) | Q(pk=old_key))
        return ScopedAdminForm

    def save_model(self, request, obj, form, change):
        save_for_user(obj, request.user)

    def changeform_view(self, request, object_id=None, form_url='', extra_context=None):
        try:
            return super().changeform_view(request, object_id, form_url, extra_context)
        except ValidationError as error:
            messages.error(request, ' '.join(error.messages))
            return HttpResponseRedirect(request.path)

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
    form = EntityForm
    # Columns to display in the list view
    list_display = ('name', 'is_customer', 'is_supplier', 'legal_kind', 'vat_number', 'is_archived')
    # Fields to filter by in the right sidebar
    list_filter = ('is_customer', 'is_supplier', 'legal_kind', 'is_archived')
    # Fields to search by
    search_fields = ('name', 'vat_number')
    readonly_fields = ('entity_type', 'vat_key', 'is_archived', 'archived_at', 'archived_by', 'record_version')

    def has_change_permission(self, request, obj=None):
        return (obj is None or not obj.is_archived) and super().has_change_permission(request, obj)

    def save_model(self, request, obj, form, change):
        saved = form.save()
        obj.__dict__.update(saved.__dict__)

    def changeform_view(self, request, object_id=None, form_url='', extra_context=None):
        try:
            return super().changeform_view(request, object_id, form_url, extra_context)
        except ValidationError as error:
            # A concurrent edit/archive may occur after ModelForm validation.
            messages.error(request, ' '.join(error.messages))
            return HttpResponseRedirect(request.path)

    def get_search_results(self, request, queryset, search_term):
        result, duplicates = super().get_search_results(request, queryset, search_term)
        from .counterparty_validation import afm_text
        import re
        key = afm_text(search_term)
        if re.fullmatch(r'[0-9]{1,9}', key):
            result = result | queryset.filter(vat_key__contains=key)
        return result, duplicates

class ReferenceAdminForm(forms.ModelForm):
    version=forms.IntegerField(required=False,min_value=0,widget=forms.HiddenInput,label='Έκδοση εγγραφής')
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        if not self.is_bound:self.initial['version']=self.instance.record_version

class AccountAdminForm(ReferenceAdminForm):
    class Meta:
        model=CashAccount
        fields='__all__'

class CategoryAdminForm(ReferenceAdminForm):
    class Meta:
        model=Category
        fields='__all__'

class ReferenceAdminMixin:
    def save_model(self,request,obj,form,change):
        from .account_services import save_reference
        if change and form.cleaned_data.get('version') is None:raise ValidationError('Ανανεώστε τη σελίδα πριν από την επεξεργασία.')
        save_reference(obj,request.user,expected_version=form.cleaned_data.get('version'))

@admin.register(CashAccount)
class CashAccountAdmin(ReferenceAdminMixin, OfficeAdminMixin, GreekAdminMixin, admin.ModelAdmin):
    form=AccountAdminForm
    readonly_fields=('opening_balance','opening_date','opening_approved_at','legacy_opening','record_version')
    list_display = ('name', 'opening_balance', 'is_active')
    list_filter = ('is_active',)

@admin.register(Category)
class CategoryAdmin(ReferenceAdminMixin, OfficeAdminMixin, GreekAdminMixin, admin.ModelAdmin):
    form=CategoryAdminForm
    readonly_fields=('record_version',)
    list_display = ('name', 'parent')
    list_filter = (('parent', OfficeRelatedFilter),)
    search_fields = ('name',)

class TransactionPostingForm(forms.ModelForm):
    amount=GreekMoneyField(max_digits=12,decimal_places=2,label='Ποσό')
    import uuid
    posting_key=forms.UUIDField(required=False,initial=uuid.uuid4,widget=forms.HiddenInput,label='Ταυτότητα καταχώρισης')
    class Meta:
        model=Transaction
        fields='__all__'


@admin.register(Transaction)
class TransactionAdmin(OfficeAdminMixin, GreekAdminMixin, admin.ModelAdmin):
    readonly_fields=('transfer_id',)
    form=TransactionPostingForm

    def save_model(self,request,obj,form,change):
        from .finance_services import submission_key
        save_for_user(obj,request.user,idempotency_key=submission_key(request,form.cleaned_data))

    list_display = ('transaction_date', 'description', 'amount', 'transaction_type', 'cash_account', 'category', 'entity')
    list_filter = ('transaction_type', ('cash_account', OfficeRelatedFilter), 'transaction_date')
    search_fields = ('description', 'entity__name')
    # Make the date have a nice hierarchy filter
    date_hierarchy = 'transaction_date'

    def has_change_permission(self,request,obj=None):
        return obj is None and super().has_change_permission(request,obj)

    def get_readonly_fields(self,request,obj=None):
        return tuple(f.name for f in self.model._meta.fields) if obj is not None else super().get_readonly_fields(request,obj)

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
