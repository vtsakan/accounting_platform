"""Operator-only real Excel antivirus/credential/preview recovery in owned PG17."""
import base64
import hashlib
import json
import secrets
import sys

import cr008_probe as prior
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

from accounting.client_import_services import confirm_import, stage_import
from accounting.cr010_models import CounterpartyImport
from accounting.models import Charge, Entity, FinanceAuditEvent, TaxisCredential, Transaction
from accounting.tests_cr010_import import workbook
from core.import_crypto import open_preview
from core.taxis_crypto import open_sealed


def upload(values):
    return SimpleUploadedFile('synthetic.xlsx', workbook([values]))


def prepare():
    result = prior.prepare()
    user = prior.get_user_model().objects.get(username='cr008-synthetic-owner')
    username, password = secrets.token_urlsafe(24), secrets.token_urlsafe(36)
    values = ['1', 'Συνθετικός', 'Πελάτης', '000000880', '00000000001', username, password,
        'Συνθετική κατάσταση', 'Συνθετική παρατήρηση', 'Χωρίς τίτλο']
    counts = (Charge.objects.count(), Transaction.objects.count(), FinanceAuditEvent.objects.count())
    row = stage_import(user, upload(values))
    assert not Entity.objects.filter(vat_key='000000880').exists()
    assert password.encode() not in bytes(row.payload)
    data = open_preview(row)
    decisions = [{'key': item['key'], 'action': 'CREATE', 'kind': 'INDIVIDUAL', 'replace_credentials': False} for item in data['rows']]
    done, replay = confirm_import(user, row.pk, decisions)
    person = Entity.objects.get(vat_key='000000880')
    assert not replay and done.outcome['created'] == 1 and person.fiscal_profile.main_amka == '00000000001'
    vault = TaxisCredential.objects.get(entity=person, subject='MAIN')
    assert open_sealed(vault) == (username, password) and bytes(done.payload) == b''
    assert person.journal_notes.count() == 1 and 'Συνθετική κατάσταση' in person.journal_notes.get().body
    assert confirm_import(user, row.pk, decisions)[1]
    assert counts == (Charge.objects.count(), Transaction.objects.count(), FinanceAuditEvent.objects.count())
    # Retain a pending SEALED preview in the encrypted dump and decrypt it after
    # the independent-key restore, as well as the final stored TaxisNet pair.
    values[3] = '000000881'
    stage_import(user, upload(values))
    before = CounterpartyImport.objects.count()
    marker = base64.b64decode('WDVPIVAlQEFQWzRcUFpYNTQoUF4pN0NDKTd9JEVJQ0FSLVNUQU5EQVJELUFOVElWSVJVUy1URVNULUZJTEUhJEgrSCo=')
    try:
        stage_import(user, SimpleUploadedFile('synthetic.xlsx', marker))
    except ValidationError as error:
        assert error.error_dict['file'][0].code == 'infected'
    else:
        raise RuntimeError('Infected Excel bytes reached preview storage')
    with override_settings(ATTACHMENT_SCANNER_HOST=''):
        try:
            stage_import(user, upload(values))
        except ValidationError:
            pass
        else:
            raise RuntimeError('Missing scanner accepted an Excel preview')
    assert CounterpartyImport.objects.count() == before
    result['snapshot'] = prior.snapshot()
    result['excel_import'] = {'clean_real_scan': True, 'eicar_denied': True, 'scanner_unavailable_denied': True,
        'explicit_confirmation': True, 'encrypted_credentials_and_preview': True, 'replay_once': True,
        'no_financial_writes': True, 'unknown_columns_retained': True}
    return result


def recovered():
    result = prior.recovered()
    row = CounterpartyImport.objects.get(state='PREVIEW')
    body = open_preview(row)
    vault = TaxisCredential.objects.get(subject='MAIN')
    pair = open_sealed(vault)
    assert pair == (body['rows'][0]['values']['username'], body['rows'][0]['values']['password'])
    result['preview_sha256'] = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    result['credential_sha256'] = hashlib.sha256(json.dumps(pair).encode()).hexdigest()
    with override_settings(SECRET_KEY=secrets.token_urlsafe(64), SECRET_KEY_FALLBACKS=[]):
        for function, record in ((open_preview, row), (open_sealed, vault)):
            try:
                function(record)
            except ValidationError:
                pass
            else:
                raise RuntimeError('A different key decrypted protected import data')
    result['excel_recovery_verified'] = True
    return result


if __name__ == '__main__':
    print(json.dumps({'prepare': prepare, 'recovered': recovered, 'snapshot': prior.snapshot}[sys.argv[1]](), ensure_ascii=False))
