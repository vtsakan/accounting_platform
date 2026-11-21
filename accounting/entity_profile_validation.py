"""Explicit local syntax and bounded tags; no external tax/health registry calls."""
import re
import unicodedata

from django.core.exceptions import ValidationError
from django.core.validators import validate_email

from .counterparty_validation import afm_key
from .entity_profile_models import CONTACT_FIELDS, FLAG_LABELS, PERSON_KINDS

KINDS = {key for key, _ in PERSON_KINDS}


def text(value, maximum, *, multiline=False):
    if not isinstance(value, str):
        raise ValidationError('Συμπληρώστε κείμενο.')
    value = value.replace('\r\n', '\n').strip()
    if len(value) > maximum or any((ord(c) < 32 and not (multiline and c in '\n\t')) or ord(c) == 127 for c in value):
        raise ValidationError('Ελέγξτε το μήκος και τους χαρακτήρες του πεδίου.')
    return value


def amka(value):
    value = str(value or '').strip().translate(str.maketrans('０１２３４５６７８９', '0123456789'))
    if value and not re.fullmatch(r'[0-9]{11}', value):
        raise ValidationError('Ο ΑΜΚΑ πρέπει να περιέχει έντεκα ψηφία ή να είναι κενός.')
    return value


def tags(value):
    if isinstance(value, str):
        value = re.split(r'[,;\n]', value)
    if not isinstance(value, (list, tuple)) or len(value) > 25:
        raise ValidationError('Προσθέστε έως 25 ετικέτες, χωρισμένες με κόμμα.')
    result = []
    seen = set()
    for item in value:
        if not isinstance(item,str):raise ValidationError('Κάθε ετικέτα πρέπει να είναι κείμενο.')
        item = text(unicodedata.normalize('NFKC', item), 40).lower()
        if item and item.casefold() not in seen:
            result.append(item)
            seen.add(item.casefold())
    return result


def profile_values(values):
    result = dict(values)
    errors = {}
    if result.get('contact_status') not in {'ACTIVE', 'INACTIVE'}:
        errors['contact_status'] = 'Επιλέξτε Ενεργός ή Ανενεργός.'
    if result.get('person_kind') not in KINDS:
        errors['person_kind'] = 'Επιλέξτε κατηγορία προσώπου.'
    for name in ('spouse_enabled', 'spouse_inherit_contacts', *FLAG_LABELS):
        if type(result.get(name)) is not bool:
            errors[name] = 'Επιλέξτε έγκυρη τιμή.'
    for name in ('main_amka', 'spouse_amka'):
        try: result[name] = amka(result.get(name))
        except ValidationError as error: errors[name] = error.messages
    for name, maximum in (('spouse_first_name', 100), ('spouse_last_name', 100), ('spouse_tax_office', 100),
            ('spouse_address', 255), ('spouse_city', 100), ('spouse_postal_code', 10),
            ('spouse_phone_number', 20), ('spouse_email', 254), ('internal_notes', 10000)):
        try: result[name] = text(result.get(name, ''), maximum, multiline=name == 'internal_notes')
        except ValidationError as error: errors[name] = error.messages
    try: result['spouse_vat_number'] = afm_key(result.get('spouse_vat_number'))
    except ValidationError as error: errors['spouse_vat_number'] = error.messages
    try: result['tags'] = tags(result.get('tags', []))
    except (ValidationError, TypeError) as error: errors['tags'] = getattr(error, 'messages', ['Ελέγξτε τις ετικέτες.'])
    if result.get('spouse_enabled'):
        for name in ('spouse_first_name', 'spouse_last_name'):
            if not result.get(name): errors[name] = 'Συμπληρώστε τα στοιχεία της συζύγου.'
        if result.get('spouse_person_kind') not in KINDS:
            errors['spouse_person_kind'] = 'Επιλέξτε κατηγορία προσώπου της συζύγου.'
        if result.get('person_kind') == 'LEGAL_ENTITY':
            errors['spouse_enabled'] = 'Η ενότητα συζύγου αφορά φυσικό πρόσωπο ή ατομική επιχείρηση.'
    else:
        for name in tuple(result):
            if name.startswith('spouse_'):
                result[name] = True if name == 'spouse_inherit_contacts' else False if name == 'spouse_enabled' else 'UNREVIEWED' if name == 'spouse_person_kind' else ''
    if result.get('spouse_inherit_contacts'):
        for name in CONTACT_FIELDS: result['spouse_' + name] = ''
    elif result.get('spouse_enabled'):
        if result.get('spouse_email'):
            try: validate_email(result['spouse_email'])
            except ValidationError: errors['spouse_email'] = 'Ελέγξτε την ηλεκτρονική διεύθυνση.'
        if result.get('spouse_phone_number') and not re.fullmatch(r'[+0-9 ()\-]{3,20}', result['spouse_phone_number']):
            errors['spouse_phone_number'] = 'Ελέγξτε το τηλέφωνο της συζύγου.'
        if result.get('spouse_postal_code') and not re.fullmatch(r'[\w -]{2,10}', result['spouse_postal_code']):
            errors['spouse_postal_code'] = 'Ελέγξτε τον ταχυδρομικό κώδικα.'
    if errors: raise ValidationError(errors)
    return result
