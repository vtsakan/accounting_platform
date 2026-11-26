"""Dated finite-budget validation shared with the authoritative PostgreSQL guard."""
from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import connection
from core.locale import format_euro

FINITE_MODES=frozenset({'ONE_OFF','ON_DEMAND'})


def budget_used(agreement,day):
    from django.db.models import Exists,OuterRef,Sum
    from .models import Charge,ChargeReversal
    from .settlement_selectors import corrections_installed
    rows=Charge.objects.filter(office_id=agreement.office_id,agreement=agreement,effective_date__lte=day)
    if corrections_installed():
        reversed_rows=ChargeReversal.objects.filter(charge_id=OuterRef('pk'),effective_date__lte=day)
        rows=rows.annotate(reversed_by_day=Exists(reversed_rows)).filter(reversed_by_day=False)
    return rows.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')


def require_capacity(agreement, day, *, amount=Decimal('0.00'), replacing=None, new_limit=None):
    # Old migration rehearsals intentionally lack this additive guard. A new
    # ON_DEMAND contract can never run on an old schema; the normal old modes
    # retain their original guards when rehearsed at those historical schemas.
    with connection.cursor() as cursor:
        cursor.execute("SELECT to_regprocedure('accounting_cr012_budget_conflict(bigint,date,numeric,uuid,numeric)') IS NOT NULL")
        installed=cursor.fetchone()[0]
        if not installed:return
        cursor.execute('SELECT * FROM accounting_cr012_budget_conflict(%s,%s,%s,%s,%s)',
            [agreement.pk,day,amount,getattr(replacing,'pk',replacing),new_limit])
        conflict=cursor.fetchone()
    if conflict:
        when,charged,limit=conflict
        raise ValidationError({'amount': 'Οι μη αντιλογισμένες χρεώσεις φτάνουν τα '+format_euro(charged)+
            ', ενώ το συμφωνημένο όριο είναι '+format_euro(limit)+' στις '+when.strftime('%d/%m/%Y')+
            '. Μειώστε τη χρέωση ή αυξήστε πρώτα το συμφωνημένο ποσό. Οι εισπράξεις δεν μειώνουν το σύνολο χρεώσεων.'})


def replacement_capacity(agreement, charge, amount, day):
    if charge.terms.billing_mode=='MONTHLY' and amount>charge.terms.agreed_amount:
        raise ValidationError({'replacement_amount':'Η αντικατάσταση δεν μπορεί να υπερβαίνει το συμφωνημένο ποσό της αρχικής μηνιαίας περιόδου ('+
            format_euro(charge.terms.agreed_amount)+').'})
    require_capacity(agreement,day,amount=amount,replacing=charge)
