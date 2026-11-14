"""Presentation composition of existing, office-scoped financial selectors."""
from django.utils import timezone

from .cash_selectors import cash_accounts
from .models import Transaction
from .movement_forms import CashMovementFilterForm
from .movement_selectors import filtered_movements, operating_movements, operating_totals
from .office_access import records


def workspace_snapshot(user, *, as_of=None):
    day = as_of if as_of is not None else timezone.localdate()
    # The retained balance selector checks office authority and the as-of date.
    accounts = list(cash_accounts(user, as_of=day))
    first = day.replace(day=1)
    form = CashMovementFilterForm({'start_date': first.isoformat(), 'end_date': day.isoformat()}, user=user)
    rows = operating_movements(filtered_movements(user, form, business_direction=True))
    return {
        'cash_accounts': accounts,
        'overview_day': day,
        'overview_start': first,
        'month_totals': operating_totals(rows),
        'pending_openings': sum(account.current_balance is None for account in accounts),
        'recent_transactions': records(Transaction, user).filter(transaction_date__lte=day)
            .select_related('cash_account', 'entity').order_by('-transaction_date', '-pk')[:6],
    }
