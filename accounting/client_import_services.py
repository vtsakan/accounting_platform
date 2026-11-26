"""Preview first; office-locked, all-or-nothing import without financial writes."""
from collections import Counter
from datetime import timedelta
import hashlib
import uuid

from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import Http404
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables

from core.client_xlsx import MAX_BYTES, XlsxError, read_workbook
from core.import_crypto import open_preview, seal
from .attachment_validation import scan_content
from .capabilities import require_capability
from .counterparty_note_services import add_note
from .counterparty_services import FIELDS, actor_scope
from .counterparty_validation import afm_key, contact_values
from .cr010_models import CounterpartyImport
from .entity_profile_models import EntityProfile, PERSON_KINDS
from .entity_profile_services import PROFILE_FIELDS, save_profile, validate_credentials
from .entity_profile_validation import amka, text
from .finance_services import audit_context, canonical, fingerprint
from .models import Entity, TaxisCredential

LABELS = {'name': 'Ονοματεπώνυμο / επωνυμία', 'vat_number': 'ΑΦΜ', 'main_amka': 'ΑΜΚΑ'}
KINDS = {key for key, _ in PERSON_KINDS}


def row_snapshot(entity):
    profile = EntityProfile.objects.filter(office_id=entity.office_id, entity=entity).first()
    vault = list(TaxisCredential.objects.filter(office_id=entity.office_id, entity=entity).order_by('subject').values_list(
        'subject', 'salt', 'sealed_username', 'sealed_password'))
    return fingerprint(canonical({'version': entity.record_version, 'archived': entity.is_archived,
        'core': {n: getattr(entity, n) for n in FIELDS},
        'profile': {n: getattr(profile, n) for n in PROFILE_FIELDS} if profile else None,
        'vault': [[v[0], *[bytes(x).hex() for x in v[1:]]] for v in vault]}))


def match(office, afm):
    # Includes archived/deleted records: never reuse an identity through an import.
    return Entity.objects.filter(office=office, vat_key=afm).first() if afm else None


@sensitive_variables('__ALL__')
def prepare_rows(office, data):
    normalized = []
    for source in data['rows']:
        try:
            value = afm_key(source['values'].get('vat_number', ''))
        except ValidationError:
            value = ''
        if value: normalized.append(value)
    counts = Counter(normalized)
    for row in data['rows']:
        source = row['values']; row['errors'] = []; row['match_id'] = None; row['snapshot'] = None
        row['name'] = ' '.join(source.get('name', '').split()) or ' '.join(
            v.strip() for v in (source.get('last_name', ''), source.get('first_name', '')) if v.strip())
        row['vat_number'] = source.get('vat_number', '').strip()
        row['main_amka'] = source.get('main_amka', '').strip()
        try:
            row['name'] = text(row['name'], 255)
            if not row['name']:
                raise ValidationError('Λείπει το ονοματεπώνυμο ή η επωνυμία.')
            row['vat_number'] = afm_key(row['vat_number']); row['main_amka'] = amka(row['main_amka'])
            contact_values({'name': row['name'], 'vat_number': row['vat_number']})
            validate_credentials({'main_taxis_username': source.get('username', ''), 'main_taxis_password': source.get('password', '')})
        except ValidationError as error:
            row['errors'].extend(error.messages)
        if row['vat_number'] and counts[row['vat_number']] > 1:
            row['errors'].append('Το ίδιο ΑΦΜ εμφανίζεται σε πολλές γραμμές του αρχείου. Κρατήστε μία γραμμή ανά ΑΦΜ.')
        old = match(office, row['vat_number']) if not row['errors'] else None
        row['kind'] = ''
        if old:
            row['match_id'] = old.pk; row['snapshot'] = row_snapshot(old)
            profile = EntityProfile.objects.filter(office=office, entity=old).first()
            row['kind'] = profile.person_kind if profile and profile.person_kind in KINDS else ''
            if old.is_archived or hasattr(old, 'deletion_record'):
                row['errors'].append('Η υπάρχουσα καρτέλα είναι αρχειοθετημένη ή διαγραμμένη. Επιτρέπεται μόνο παράλειψη.')
        elif source.get('first_name', '').strip():
            row['kind'] = 'INDIVIDUAL'
        if not row['vat_number']:
            row['warnings'].append('Χωρίς ΑΦΜ: δεν γίνεται αυτόματη ταυτοποίηση. Ελέγξτε αν υπάρχει ήδη καρτέλα.')
    return data


@sensitive_variables('__ALL__')
def stage_import(user, upload):
    require_capability(user, 'clients.write'); require_capability(user, 'clients.credentials')
    if upload is None or not str(upload.name).lower().endswith('.xlsx'):
        raise ValidationError('Επιλέξτε αρχείο .xlsx.')
    pieces = []; size = 0
    for part in upload.chunks(64 * 1024):
        size += len(part)
        if size > MAX_BYTES:
            raise ValidationError('Επιτρέπονται αρχεία έως 5 μεγαμπάιτ.')
        pieces.append(part)
    payload = b''.join(pieces)
    if not payload:
        raise ValidationError('Το αρχείο είναι κενό.')
    # Reuse the private, fail-closed real antivirus already deployed for uploads.
    scan_content(payload)
    try:
        data = read_workbook(payload)
    except (XlsxError, KeyError, ValueError, OverflowError):
        raise ValidationError('Το βιβλίο δεν είναι έγκυρο ή υπερβαίνει τα όρια. Χρησιμοποιήστε έως 250 γραμμές, χωρίς τύπους ή μακροεντολές.') from None
    digest = 'sha256:' + hashlib.sha256(payload).hexdigest()
    with transaction.atomic():
        office = actor_scope(user); require_capability(user, 'clients.credentials')
        with audit_context(user, 'Προεπισκόπηση εισαγωγής πελατών'):
            CounterpartyImport.objects.filter(office=office, actor=user, state='PREVIEW', expires_at__lte=timezone.now()).update(
                state='CANCELLED', payload=b'', salt=b'', completed_at=timezone.now())
            if CounterpartyImport.objects.filter(office=office, source_sha256=digest, state='DONE').exclude(outcome__created=0, outcome__updated=0).exists():
                raise ValidationError('Το ίδιο ακριβώς αρχείο έχει ήδη εισαχθεί στο γραφείο. Ελέγξτε τις καρτέλες πριν από νέα εισαγωγή.')
            row = CounterpartyImport(office=office, actor=user, source_sha256=digest, expires_at=timezone.now()+timedelta(minutes=30))
            seal(row, prepare_rows(office, data)); row.save()
    return row


def owned_import(user, key, *, lock=False):
    profile = require_capability(user, 'clients.write'); require_capability(user, 'clients.credentials')
    try:
        query = CounterpartyImport.objects.select_for_update() if lock else CounterpartyImport.objects
        return query.get(pk=key, office_id=profile.office_id, actor_id=user.pk)
    except (CounterpartyImport.DoesNotExist, ValueError, TypeError, ValidationError):
        raise Http404('Η προεπισκόπηση δεν βρέθηκε.') from None


def current_preview(user, key):
    row = owned_import(user, key)
    if row.state != 'PREVIEW':
        return row, None
    if row.expires_at <= timezone.now():
        raise ValidationError('Η προεπισκόπηση έληξε. Ανεβάστε ξανά το αρχείο.')
    return row, open_preview(row)


def display_rows(office, data):
    """Only a whitelist reaches HTML. No username/password in HTML or sessions."""
    result = []
    for row in data['rows']:
        old = Entity.objects.filter(office=office, pk=row['match_id']).first() if row['match_id'] else None
        profile = EntityProfile.objects.filter(office=office, entity=old).first() if old else None
        result.append({k: row[k] for k in ('key', 'sheet', 'row', 'name', 'vat_number', 'main_amka',
            'errors', 'warnings', 'extras', 'kind', 'match_id')} | {
            'before_name': old.name if old else '', 'before_amka': profile.main_amka if profile else '',
            'has_credentials': bool(row['values'].get('username') and row['values'].get('password')),
            'existing_credentials': bool(old and TaxisCredential.objects.filter(office=office, entity=old, subject='MAIN').exists())})
    return result


def note_parts(row):
    content = '\n'.join(label+': '+value for label, value in row['extras'])
    # Retain all unknown values, including nonempty columns without a header.
    while content:
        part, content = content[:4900], content[4900:]
        yield 'Στοιχεία αρχείου:\n' + part + '\nΤέλος στοιχείων.'


@transaction.atomic
@sensitive_variables('__ALL__')
def confirm_import(user, key, decisions):
    office = actor_scope(user); require_capability(user, 'clients.credentials')
    row = owned_import(user, key, lock=True)
    if not isinstance(decisions, list) or any(not isinstance(d, dict) or set(d) != {'key', 'action', 'kind', 'replace_credentials'} for d in decisions):
        raise ValidationError('Η επιλογή εισαγωγής δεν είναι έγκυρη.')
    digest = fingerprint(canonical(decisions))
    if row.state == 'DONE':
        if row.decisions_sha256 != digest:
            raise ValidationError('Η εισαγωγή ολοκληρώθηκε με διαφορετικές επιλογές.')
        return row, True
    if row.state != 'PREVIEW' or row.expires_at <= timezone.now():
        raise ValidationError('Η προεπισκόπηση έληξε ή ακυρώθηκε. Ανεβάστε ξανά το αρχείο.')
    if CounterpartyImport.objects.filter(office=office, source_sha256=row.source_sha256, state='DONE').exclude(pk=row.pk).exclude(outcome__created=0, outcome__updated=0).exists():
        raise ValidationError('Το ίδιο αρχείο ολοκληρώθηκε ήδη από άλλη προεπισκόπηση.')
    data = open_preview(row); rows = data['rows']
    if [d['key'] for d in decisions] != [r['key'] for r in rows]:
        raise ValidationError('Ελέγξτε μία επιλογή για κάθε γραμμή της προεπισκόπησης.')
    outcome = {'created': 0, 'updated': 0, 'skipped': 0, 'notes': 0}
    for item, decision in zip(rows, decisions):
        action = decision['action']; kind = decision['kind']; replace = decision['replace_credentials']
        if action not in {'CREATE', 'UPDATE', 'SKIP'} or type(replace) is not bool:
            raise ValidationError('Μη έγκυρη ενέργεια εισαγωγής.')
        if action == 'SKIP':
            outcome['skipped'] += 1
            continue
        if item['errors'] or kind not in KINDS or action != ('UPDATE' if item['match_id'] else 'CREATE'):
            raise ValidationError('Ελέγξτε τις επιλεγμένες γραμμές και την κατηγορία προσώπου.')
        entity = match(office, item['vat_number'])
        if (entity.pk if entity else None) != item['match_id']:
            raise ValidationError('Οι καρτέλες άλλαξαν μετά την προεπισκόπηση. Ανεβάστε ξανά το αρχείο.')
        if entity:
            entity = Entity.objects.select_for_update().get(office=office, pk=entity.pk)
            if entity.is_archived or row_snapshot(entity) != item['snapshot']:
                raise ValidationError('Η καρτέλα άλλαξε μετά την προεπισκόπηση. Ανεβάστε ξανά το αρχείο.')
        base = entity or Entity(office=office, is_customer=True, is_supplier=False)
        core = {n: getattr(base, n) for n in FIELDS}
        core.update(name=item['name'])
        if item['vat_number']:
            core['vat_number'] = item['vat_number']
        old_profile = EntityProfile.objects.filter(office=office, entity=entity).first() if entity else None
        values = {n: getattr(old_profile or EntityProfile(), n) for n in PROFILE_FIELDS}
        values['person_kind'] = kind
        if item['main_amka']:
            values['main_amka'] = item['main_amka']
        credentials = {}
        if (not entity or replace) and item['values'].get('username'):
            credentials = {'main_taxis_username': item['values']['username'], 'main_taxis_password': item['values']['password']}
        entity = save_profile(user, core, values, credentials, key=entity.pk if entity else None,
            version=entity.record_version if entity else 0)
        outcome['updated' if action == 'UPDATE' else 'created'] += 1
        for index, part in enumerate(note_parts(item)):
            add_note(user, entity.pk, subject=('Εισαγωγή Excel · '+item['sheet']+' · γραμμή '+str(item['row']))[:200],
                body=part, request_key=uuid.uuid5(row.pk, item['key']+':'+str(index)))
            outcome['notes'] += 1
    with audit_context(user, 'Ολοκλήρωση εισαγωγής πελατών'):
        row.state = 'DONE'; row.decisions_sha256 = digest; row.outcome = outcome
        row.completed_at = timezone.now(); row.payload = b''; row.salt = b''; row.save()
    return row, False


@transaction.atomic
def cancel_import(user, key):
    actor_scope(user)
    row = owned_import(user, key, lock=True)
    if row.state == 'PREVIEW':
        with audit_context(user, 'Ακύρωση προεπισκόπησης'):
            row.state = 'CANCELLED'; row.completed_at = timezone.now(); row.payload = b''; row.salt = b''; row.save()
    return row
