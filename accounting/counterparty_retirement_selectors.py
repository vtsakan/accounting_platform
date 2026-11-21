"""Shared SQL archive decision and exclusion of owner-deleted identities."""
from django.db import connection
from django.utils import timezone

OPEN_AGREEMENT = 'Δεν επιτρέπεται η αρχειοθέτηση: υπάρχει ανοιχτή συμφωνία. Ελέγξτε τις χρεώσεις, τις εξοφλήσεις και τη λήξη των όρων της.'
FINANCIAL_HISTORY = 'Δεν επιτρέπεται η διαγραφή: υπάρχει οικονομικό ιστορικό, συμφωνίες ή κινήσεις. Το ιστορικό διατηρείται με την αρχειοθέτηση.'
DELETED = 'Η εγγραφή έχει διαγραφεί και δεν είναι διαθέσιμη για νέα εργασία ή επαναφορά.'


def retirement_installed():
    # Historical migration contracts deliberately use the old schemas. This
    # checks the actual catalog, never an input/flag/cache that could hide rows.
    if connection.vendor != 'postgresql':
        return False
    with connection.cursor() as cursor:
        cursor.execute("""SELECT to_regclass('accounting_counterpartydeletion') IS NOT NULL,
            to_regprocedure('accounting_cr005_open_agreements(bigint,uuid,date)') IS NOT NULL
            AND to_regprocedure('accounting_cr005_financial_history(bigint)') IS NOT NULL
            AND EXISTS(SELECT 1 FROM pg_trigger WHERE tgname='cr005_entity_guard'
                AND tgrelid=to_regclass('accounting_entity') AND tgenabled='O')
            AND EXISTS(SELECT 1 FROM pg_trigger WHERE tgname='cr005_deletion_guard'
                AND tgrelid=to_regclass('accounting_counterpartydeletion') AND tgenabled='O')""")
        table, guarded = cursor.fetchone()
    if table and not guarded:
        raise RuntimeError('Η αναβάθμιση της βάσης για αρχειοθέτηση και διαγραφή δεν έχει ολοκληρωθεί.')
    return table


def visible_counterparties(queryset):
    if not retirement_installed():
        return queryset
    from .models import CounterpartyDeletion
    return queryset.exclude(pk__in=CounterpartyDeletion.objects.values('entity_id'))


def deleted(entity):
    if not retirement_installed():
        return False
    from .models import CounterpartyDeletion
    return CounterpartyDeletion.objects.filter(office_id=entity.office_id, entity_id=entity.pk).exists()


def archive_blockers(entity):
    if not retirement_installed():
        return []  # Only an exact pre-CR005 historical schema has no new rule.
    with connection.cursor() as cursor:
        cursor.execute('SELECT agreement_id, reason FROM accounting_cr005_open_agreements(%s,%s,%s)',
            [entity.pk, entity.office_id, timezone.localdate()])
        values = cursor.fetchall()
    reasons = {
        'outstanding': 'Υπάρχει ανεξόφλητη χρέωση',
        'future': 'Υπάρχει προγραμματισμένη ενεργή συμφωνία',
        'monthly': 'Η μηνιαία συμφωνία παραμένει ενεργή',
        'review': 'Εκκρεμεί έλεγχος ή ολοκλήρωση των όρων',
        'one_off': 'Η εφάπαξ συμφωνία δεν έχει εξοφληθεί ή λήξει',
    }
    return [{'pk': key, 'reason': reasons[reason]} for key, reason in values]


def has_financial_history(entity):
    # Any historical agreement/terms/charge/cash counts, including cancelled,
    # fully settled, refunded or reversed rows; a zero balance is insufficient.
    from django.db.models import Q
    from .models import Agreement, AgreementTermsVersion, Charge, FinanceAuditEvent, Transaction
    if any(model.objects.filter(entity_id=entity.pk).exists()
            for model in (Agreement, AgreementTermsVersion, Charge, Transaction)):
        return True
    return FinanceAuditEvent.objects.filter(office_id=entity.office_id).filter(
        Q(before__entity_id=entity.pk) | Q(after__entity_id=entity.pk)).exists()
