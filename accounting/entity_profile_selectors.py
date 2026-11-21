"""Live fiscal profiles and canonical, direction-separated financial balances."""
from decimal import Decimal

from django.db import connection
from django.db.models import Q, Sum
from django.utils import timezone

from .capabilities import require_capability
from .entity_profile_models import CONTACT_FIELDS
from .models import Entity


def profile_installed():
    if connection.vendor != 'postgresql': return False
    with connection.cursor() as cursor:
        cursor.execute("""SELECT (to_regclass('accounting_entityprofile') IS NOT NULL)::int
          +(to_regclass('accounting_taxiscredential') IS NOT NULL)::int
          +(to_regclass('accounting_entityprofileevent') IS NOT NULL)::int,
          (SELECT count(*) FROM django_migrations WHERE app='accounting'
            AND name IN ('0033_entity_fiscal_profile','0034_entity_profile_guards')),
          (SELECT count(*) FROM pg_trigger WHERE NOT tgisinternal AND tgenabled='O'
            AND (tgname='cr007_profile_guard' AND tgrelid=to_regclass('accounting_entityprofile')
             OR tgname='cr007_credential_guard' AND tgrelid=to_regclass('accounting_taxiscredential')
             OR tgname='cr007_profile_event_guard' AND tgrelid=to_regclass('accounting_entityprofileevent')
             OR tgname='cr007_profile_audit' AND tgrelid=to_regclass('accounting_entityprofile')
             OR tgname='cr007_credential_audit' AND tgrelid=to_regclass('accounting_taxiscredential')))""")
        tables, migrations, guards = cursor.fetchone()
    if (tables or migrations or guards) and (tables, migrations, guards) != (3, 2, 5):
        raise RuntimeError('Η αναβάθμιση των στοιχείων οντότητας δεν έχει ολοκληρωθεί.')
    return tables == 3


def profile_for(entity):
    if not profile_installed(): return None
    from .models import EntityProfile
    return EntityProfile.objects.filter(office_id=entity.office_id, entity=entity).first()


def spouse_contacts(entity, profile):
    return {name: getattr(entity, name) if profile.spouse_inherit_contacts else getattr(profile, 'spouse_' + name)
        for name in CONTACT_FIELDS}


def contact_status(entity):
    profile = profile_for(entity)
    return profile.contact_status if profile else 'ACTIVE'


def decorate_profiles(rows):
    rows = list(rows)
    if not rows or not profile_installed(): return rows
    from .models import EntityProfile
    profiles = {p.entity_id: p for p in EntityProfile.objects.filter(
        office_id=rows[0].office_id, entity_id__in=[e.pk for e in rows])}
    for entity in rows:
        entity.profile_summary = profiles.get(entity.pk)
        entity.contact_status_label = entity.profile_summary.get_contact_status_display() if entity.profile_summary else 'Ενεργός'
        entity.person_kind_label = entity.profile_summary.get_person_kind_display() if entity.profile_summary else entity.get_legal_kind_display()
    return rows


def tags_in_office(user):
    profile = require_capability(user, 'clients.read')
    if not profile_installed(): return []
    with connection.cursor() as cursor:
        cursor.execute("""SELECT DISTINCT jsonb_array_elements_text(p.tags) AS tag
          FROM accounting_entityprofile p WHERE p.office_id=%s
          AND NOT EXISTS(SELECT 1 FROM accounting_counterpartydeletion d WHERE d.entity_id=p.entity_id)
          ORDER BY tag LIMIT 1000""", [profile.office_id])
        return [row[0] for row in cursor.fetchall()]


def filter_profiles(rows, values):
    if not profile_installed(): return rows
    status = values.get('contact_status') or 'ACTIVE'
    if status == 'ACTIVE':
        rows = rows.exclude(fiscal_profile__contact_status='INACTIVE')
    elif status == 'INACTIVE':
        rows = rows.filter(fiscal_profile__contact_status='INACTIVE')
    kind = values.get('person_kind')
    if kind:
        condition=Q(fiscal_profile__person_kind=kind)
        if kind=='INDIVIDUAL':condition|=Q(fiscal_profile__isnull=True,legal_kind='INDIVIDUAL')
        rows=rows.filter(condition)
    selected = values.get('tags') or []
    if selected:
        if values.get('tag_mode') == 'ANY':
            condition = Q(pk__in=[])
            for tag in selected: condition |= Q(fiscal_profile__tags__contains=[tag])
            rows = rows.filter(condition)
        else: rows = rows.filter(fiscal_profile__tags__contains=selected)
    for name in ('liable_a21','prefilled_return','disability','rent_subsidy','rented_home','student_allowance'):
        if values.get(name): rows = rows.filter(**{'fiscal_profile__' + name: True})
    return rows


def financial_summary(user, entity, *, as_of=None):
    from .settlement_selectors import settlement_totals
    day = as_of or timezone.localdate()
    values = settlement_totals(user, entity=entity, as_of=day)
    return {**values, 'as_of': day,
        'customer_payments': values['receivable_allocated'] + values['customer_credit'],
        'supplier_payments': values['payable_allocated'] + values['supplier_advance'],
        'customer_balance': values['receivable_remaining'] - values['customer_credit'],
        'supplier_balance': values['payable_remaining'] - values['supplier_advance']}


def bulk_balances(user, entities, *, as_of):
    """Two bounded grouped reads, sharing the retained dated/reversal selectors."""
    from .settlement_selectors import _charge_balances, _cash_sources
    office = require_capability(user, 'finance.read').office_id
    ids = [e.pk for e in entities]
    result = {key: {'customer_balance': Decimal('0.00'), 'supplier_balance': Decimal('0.00')} for key in ids}
    charges = _charge_balances(office, as_of=as_of).filter(entity_id__in=ids).order_by().values('entity_id','direction').annotate(amount=Sum('outstanding'))
    for row in charges:
        result[row['entity_id']]['customer_balance' if row['direction']=='RECEIVABLE' else 'supplier_balance'] += row['amount']
    sources = _cash_sources(office, as_of=as_of).filter(entity_id__in=ids).order_by().values('entity_id','transaction_type').annotate(amount=Sum('available_credit'))
    for row in sources:
        result[row['entity_id']]['customer_balance' if row['transaction_type']=='INCOME' else 'supplier_balance'] -= row['amount']
    return result
