"""One exact, dated cash definition for dashboards, workspace and future reports."""
from datetime import date
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db.models import OuterRef,Subquery,Sum,Value,F,Q,Case,When,DecimalField
from django.db.models.functions import Coalesce
from django.utils import timezone
from .capabilities import require_capability
from .models import CashAccount,CashAdjustment,Transaction
from .movement_selectors import operating_movements,internal_transfer_condition


def cash_accounts(user,*,as_of=None,include_inactive=False):
    office=require_capability(user,'finance.read').office_id
    day=as_of if as_of is not None else timezone.localdate()
    if type(day) is not date or day>timezone.localdate():raise ValidationError('Επιλέξτε έγκυρη ημερομηνία υπολοίπου έως σήμερα.')
    cash=Transaction.objects.filter(office_id=office,cash_account_id=OuterRef('pk'),transaction_date__gte=OuterRef('opening_date'),transaction_date__lte=day).order_by()
    def total(query,group):
        return Coalesce(Subquery(query.values(group).annotate(value=Sum('amount')).values('value'),output_field=DecimalField()),Value(Decimal('0.00')),output_field=DecimalField())
    adjustments=CashAdjustment.objects.filter(office_id=office,account_id=OuterRef('pk'),effective_date__gte=OuterRef('opening_date'),effective_date__lte=day).order_by()
    qs=CashAccount.objects.filter(office_id=office)
    if not include_inactive:qs=qs.filter(is_active=True)
    operating=operating_movements(cash)
    internal=cash.filter(internal_transfer_condition())
    # total_income/expense retain their original cash-flow meaning for balances.
    # New projections make the transfer/operating distinction explicit without
    # removing either leg from its own account's dated cash balance.
    return qs.annotate(total_income=total(cash.filter(transaction_type='INCOME'),'cash_account_id'),
        total_expense=total(cash.filter(transaction_type='EXPENSE'),'cash_account_id'),
        operating_income=total(operating.filter(transaction_type='INCOME'),'cash_account_id'),
        operating_expense=total(operating.filter(transaction_type='EXPENSE'),'cash_account_id'),
        transfer_in=total(internal.filter(transaction_type='INCOME'),'cash_account_id'),
        transfer_out=total(internal.filter(transaction_type='EXPENSE'),'cash_account_id'),
        adjustment_total=total(adjustments,'account_id')).annotate(current_balance=Case(
            When(opening_date__isnull=False,opening_date__lte=day,then=F('opening_balance')+F('total_income')-F('total_expense')+F('adjustment_total')),
            default=Value(None),output_field=DecimalField())).order_by('name','pk')
