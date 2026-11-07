# accounting/admin.py

from django.contrib import admin
from .models import Entity, CashAccount, Category, Transaction, Agreement
from django.utils.translation import gettext

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
class EntityAdmin(GreekAdminMixin, admin.ModelAdmin):
    # Columns to display in the list view
    list_display = ('name', 'entity_type', 'vat_number', 'phone_number')
    # Fields to filter by in the right sidebar
    list_filter = ('entity_type',)
    # Fields to search by
    search_fields = ('name', 'vat_number')

@admin.register(CashAccount)
class CashAccountAdmin(GreekAdminMixin, admin.ModelAdmin):
    list_display = ('name', 'opening_balance', 'is_active')
    list_filter = ('is_active',)

@admin.register(Category)
class CategoryAdmin(GreekAdminMixin, admin.ModelAdmin):
    list_display = ('name', 'parent')
    list_filter = ('parent',)
    search_fields = ('name',)

@admin.register(Transaction)
class TransactionAdmin(GreekAdminMixin, admin.ModelAdmin):
    list_display = ('transaction_date', 'description', 'amount', 'transaction_type', 'cash_account', 'category', 'entity')
    list_filter = ('transaction_type', 'cash_account', 'transaction_date')
    search_fields = ('description', 'entity__name')
    # Make the date have a nice hierarchy filter
    date_hierarchy = 'transaction_date'

@admin.register(Agreement)
class AgreementAdmin(GreekAdminMixin, admin.ModelAdmin):
    # Columns to display in the list view
    list_display = ('entity', 'agreement_type', 'total_amount', 'status', 'start_date')
    # Fields to filter by in the right sidebar
    list_filter = ('agreement_type', 'status')
    # Fields to search by
    search_fields = ('entity__name', 'description')
    # Make the date have a nice hierarchy filter
    date_hierarchy = 'start_date'
