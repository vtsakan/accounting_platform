"""Office-locked, append-only S27 configuration. Preview never posts money."""
from datetime import date
import re
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from .capabilities import require_capability
from .charge_services import period_start, source_identity
from .correction_selectors import terms_on
from .fee_models import ServiceItem, ServicePrice, FeeSchedule, FeeScheduleVersion
from .finance_money import money
from .finance_services import audit_context, clean_reason, scoped_lock
from .models import Agreement, AgreementTermsVersion, Charge, ChargeReversal, Entity, FinancePeriodClose
from .office_access import locked_office


def month(value):
    result = period_start(value)
    if result is None:
        raise ValidationError('Επιλέξτε μήνα στη μορφή ΕΕΕΕ-ΜΜ.')
    return result


def next_month(value):
    if value.year >= 9999 and value.month == 12:
        raise ValidationError('Ο μήνας βρίσκεται εκτός υποστηριζόμενου εύρους.')
    return date(value.year + (value.month == 12), value.month % 12 + 1, 1)


def price_on(service, day=None):
    return service.prices.filter(office_id=service.office_id, effective_date__lte=day or timezone.localdate()).first()


def catalogue(user):
    return ServiceItem.objects.filter(office_id=require_capability(user, 'finance.read').office_id).order_by('code')


@transaction.atomic
def save_price(user, *, code=None, service_id=None, expected_revision=0, description, amount, effective_date, is_active=True, reason):
    office = locked_office(user, 'office.settings')
    amount, reason = money(amount), clean_reason(reason)
    if not isinstance(description, str) or not description.strip() or len(description) > 255 or type(is_active) is not bool:
        raise ValidationError('Συμπληρώστε έγκυρη περιγραφή και κατάσταση υπηρεσίας.')
    if type(effective_date) is not date or effective_date < timezone.localdate() or type(expected_revision) is not int:
        raise ValidationError('Η νέα τιμή ισχύει από σήμερα ή μελλοντικά. Ανανεώστε την έκδοση.')
    with audit_context(user, reason):
        if service_id is None:
            if not isinstance(code, str) or not re.fullmatch(r'[A-Z0-9][A-Z0-9._-]{0,39}', code) or expected_revision != 0:
                raise ValidationError('Ο κωδικός έχει έως 40 λατινικούς κεφαλαίους χαρακτήρες, ψηφία ή ._- .')
            if ServiceItem.objects.filter(office=office, code=code).exists():
                raise ValidationError('Ο κωδικός υπηρεσίας υπάρχει ήδη.')
            service = ServiceItem.objects.create(office=office, code=code, actor=user, reason=reason)
            latest = None
        else:
            service = scoped_lock(ServiceItem, office, service_id)
            latest = service.prices.first()
        if (latest.revision if latest else 0) != expected_revision or (latest and effective_date < latest.effective_date):
            raise ValidationError('Η τιμή άλλαξε ή προηγείται άλλης προγραμματισμένης τιμής. Ανανεώστε τη σελίδα.')
        return ServicePrice.objects.create(office=office, service=service, revision=expected_revision + 1,
            description=description.strip(), amount=amount, effective_date=effective_date, is_active=is_active, actor=user, reason=reason)


def monthly_terms(office, agreement, period):
    if agreement.office_id != office.pk or agreement.agreement_type != 'RECEIVABLE':
        raise ValidationError('Απαιτείται εισπρακτέα συμφωνία του γραφείου.')
    entity = scoped_lock(Entity, office, agreement.entity_id, active=True)
    if not entity.is_customer:
        raise ValidationError('Απαιτείται ενεργός πελάτης.')
    terms = terms_on(agreement, max(period, agreement.start_date))
    if terms is None or terms.billing_mode != 'MONTHLY' or terms.lifecycle != 'ACTIVE' or agreement.status == 'CANCELLED':
        raise ValidationError('Απαιτούνται ελεγμένοι ενεργοί μηνιαίοι όροι συμφωνίας.')
    return terms


def schedule_values(*, effective_period, end_period, due_day, due_next_month):
    effective_period = month(effective_period)
    end_period = month(end_period) if end_period not in (None, '') else None
    if end_period and end_period < effective_period:
        raise ValidationError('Ο τελευταίος μήνας δεν προηγείται του μήνα έναρξης ισχύος.')
    if type(due_day) is not int or not 1 <= due_day <= 28 or type(due_next_month) is not bool:
        raise ValidationError('Επιλέξτε ημέρα προθεσμίας 1–28 και τον μήνα της προθεσμίας.')
    return effective_period, end_period


@transaction.atomic
def create_schedule(user, *, agreement_id, start_period, end_period=None, due_day=15, due_next_month=False, first_amount=None, reason):
    office = locked_office(user, 'finance.write')
    start_period, end_period = schedule_values(effective_period=start_period, end_period=end_period, due_day=due_day, due_next_month=due_next_month)
    reason = clean_reason(reason)
    agreement = scoped_lock(Agreement, office, agreement_id)
    if start_period < agreement.start_date.replace(day=1):
        raise ValidationError('Το πρόγραμμα δεν προηγείται της συμφωνίας.')
    terms = monthly_terms(office, agreement, start_period)
    partial = start_period == agreement.start_date.replace(day=1) and agreement.start_date.day != 1
    if partial and first_amount is None:
        raise ValidationError('Επιβεβαιώστε ρητά το ποσό του πρώτου μη πλήρους μήνα.')
    if not partial and first_amount is not None:
        raise ValidationError('Το ειδικό πρώτο ποσό αφορά μόνο τον πρώτο μη πλήρη μήνα της συμφωνίας.')
    first_amount = money(first_amount) if partial else None
    if partial and not due_next_month and due_day < agreement.start_date.day:
        raise ValidationError('Η πρώτη προθεσμία προηγείται της έναρξης. Επιλέξτε προθεσμία στον επόμενο μήνα.')
    if FeeSchedule.objects.filter(agreement=agreement).exists():
        raise ValidationError('Υπάρχει ήδη πρόγραμμα για αυτή τη συμφωνία. Χρησιμοποιήστε το ιστορικό αλλαγών του.')
    with audit_context(user, reason):
        schedule = FeeSchedule.objects.create(office=office, agreement=agreement, start_period=start_period,
            first_amount=first_amount, actor=user, reason=reason)
        FeeScheduleVersion.objects.create(office=office, schedule=schedule, revision=1, effective_period=start_period,
            end_period=end_period, due_day=due_day, due_next_month=due_next_month, terms_snapshot=terms, actor=user, reason=reason)
    return schedule


@transaction.atomic
def change_schedule(request, *, schedule_id, expected_revision, effective_period, end_period=None,
                    due_day=15, due_next_month=False, cancelled=False, password, reason):
    office = locked_office(request.user, 'finance.amend')
    from .office_services import prove_actor
    prove_actor(request, office, password, 'finance.amend')
    effective_period, end_period = schedule_values(effective_period=effective_period, end_period=end_period,
        due_day=due_day, due_next_month=due_next_month)
    if type(cancelled) is not bool or effective_period <= timezone.localdate().replace(day=1):
        raise ValidationError('Η αλλαγή προγράμματος ισχύει από επόμενο ημερολογιακό μήνα.')
    schedule = scoped_lock(FeeSchedule, office, schedule_id)
    agreement = scoped_lock(Agreement, office, schedule.agreement_id)
    latest = schedule.versions.first()
    if latest.cancelled or type(expected_revision) is not int or latest.revision != expected_revision or effective_period <= latest.effective_period:
        raise ValidationError('Το πρόγραμμα άλλαξε ή έχει διακοπεί. Ανανεώστε τη σελίδα.')
    # The rate itself is changed only through S24's owner/MFA terms amendment.
    terms = terms_on(agreement, effective_period)
    if terms is None:
        raise ValidationError('Δεν υπάρχουν ελεγμένοι όροι για την περίοδο.')
    if not cancelled:
        terms = monthly_terms(office, agreement, effective_period)
    reason = clean_reason(reason)
    with audit_context(request.user, reason):
        return FeeScheduleVersion.objects.create(office=office, schedule=schedule, revision=expected_revision + 1,
            effective_period=effective_period, end_period=end_period, due_day=due_day, due_next_month=due_next_month,
            cancelled=cancelled, terms_snapshot=terms, actor=request.user, reason=reason)


def schedules(user):
    return FeeSchedule.objects.filter(office_id=require_capability(user, 'finance.read').office_id).select_related('agreement__entity').order_by('-recorded_at')


def preview(user, schedule_id, *, start_period=None, months=12):
    """At most 24 periods; every source identity survives versions and reversal."""
    office = require_capability(user, 'finance.read').office_id
    if type(months) is not int or not 1 <= months <= 24:
        raise ValidationError('Η προεπισκόπηση καλύπτει 1–24 μήνες.')
    schedule = FeeSchedule.objects.filter(office_id=office, pk=schedule_id).select_related('agreement__entity').first()
    if schedule is None:
        raise ValidationError('Το πρόγραμμα δεν βρέθηκε.')
    period = month(start_period) if start_period else max(schedule.start_period, timezone.localdate().replace(day=1))
    versions = list(schedule.versions.order_by('revision'))
    agreement = schedule.agreement
    close = FinancePeriodClose.objects.filter(office_id=office).order_by('-closed_through').first()
    result = []
    for _ in range(months):
        after = next_month(period)
        version = next((v for v in reversed(versions) if v.effective_period <= period), None)
        source = source_identity(agreement.pk, 'MONTHLY', period)
        charge = Charge.objects.filter(office_id=office, source_key=source).first()
        day = max(period, agreement.start_date)
        terms = terms_on(agreement, day)
        changes = AgreementTermsVersion.objects.filter(office_id=office, agreement=agreement,
            effective_date__gt=day, effective_date__lt=after).exists()
        amount = terms.agreed_amount if terms else None
        if period == schedule.start_period and schedule.first_amount is not None:
            amount = schedule.first_amount
        due = (next_month(period) if version and version.due_next_month else period).replace(day=version.due_day if version else 1)
        state, label = 'ready', 'Προγραμματισμένη — δεν έχει καταχωριστεί'
        if charge:
            reversed_charge = ChargeReversal.objects.filter(office_id=office, charge=charge).exists()
            state, label = ('reversed', 'Αντιλογισμένη — η πηγή διατηρείται') if reversed_charge else ('posted', 'Ήδη καταχωρισμένη')
            amount, terms = charge.amount, charge.terms
            day, due = charge.effective_date, charge.due_date
        elif version is None or period < schedule.start_period or version.cancelled or (version.end_period and period > version.end_period):
            state, label = 'outside', 'Εκτός ενεργού προγράμματος'
        elif agreement.entity.is_archived or not agreement.entity.is_customer or agreement.status == 'CANCELLED' or terms is None or terms.billing_mode != 'MONTHLY' or terms.lifecycle != 'ACTIVE':
            state, label = 'blocked', 'Μη ενεργός πελάτης ή όροι συμφωνίας'
        elif changes or due < day:
            state, label = 'review', 'Απαιτείται ρητός έλεγχος μερικής περιόδου ή προθεσμίας'
        elif close and day <= close.closed_through:
            state, label = 'closed', 'Κλεισμένη οικονομική περίοδος'
        result.append({'period':period, 'effective_date':day, 'due_date':due, 'amount':amount,
            'description':charge.description if charge else (terms.description if terms else ''), 'terms_revision':terms.revision if terms else None,
            'source_key':source, 'state':state, 'label':label, 'charge_id':charge.pk if charge else None})
        period = after
    return result
