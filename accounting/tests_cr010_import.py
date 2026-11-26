"""Synthetic XLSX/import contracts for the operator PG17 gate. No client data."""
from datetime import timedelta
import io
import secrets
import uuid
from unittest.mock import patch
from xml.sax.saxutils import escape
import zipfile

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import DatabaseError, transaction
from django.http import Http404
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.client_xlsx import XlsxError, column_label, read_workbook
from core.import_crypto import open_preview, seal
from core.taxis_crypto import open_sealed
from .client_import_services import cancel_import, confirm_import, current_preview, stage_import
from .counterparty_note_services import add_note
from .cr010_models import CounterpartyImport
from .finance_services import audit_context
from .membership import create_accountant_profile
from .auth_policy import state_for
from .models import AccountantProfile, Charge, CounterpartyNote, Entity, EntityProfile, FinanceAuditEvent, TaxisCredential, Transaction
from .tests_entity_profile import ProfileSupport

HEADERS = ['Α/Α', 'ΕΠΩΝΥΜΟ', 'ΟΝΟΜΑ', 'ΑΦΜ', 'ΑΜΚΑ', 'USERNAME', 'PASSWORD', 'ΚΑΤΑΣΤΑΣΗ 1', 'ΠΑΡΑΤΗΡΗΣΕΙΣ', '']


def workbook(rows, headers=None, *, formula=False):
    """Minimal synthetic OOXML fixture, generated in memory only by the operator."""
    body = []
    for number, values in enumerate([HEADERS if headers is None else headers, *rows], 1):
        cells = []
        for col, value in enumerate(values, 1):
            address = column_label(col)+str(number)
            if isinstance(value, int):
                cells.append('<c r="'+address+'"><v>'+str(value)+'</v></c>')
            else:
                cells.append('<c r="'+address+'" t="inlineStr"><is><t xml:space="preserve">'+escape(str(value))+'</t></is></c>')
        if formula and number == 2:
            cells.append('<c r="Z2"><f>1+1</f><v>2</v></c>')
        body.append('<row r="'+str(number)+'">'+''.join(cells)+'</row>')
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="xml" ContentType="application/xml"/></Types>')
        z.writestr('xl/workbook.xml', '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Πελάτες" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Target="worksheets/sheet1.xml" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"/></Relationships>')
        z.writestr('xl/worksheets/sheet1.xml', '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'+''.join(body)+'</sheetData></worksheet>')
    return data.getvalue()


def seed_import_routes(cls):
    for suffix, actors in (('a', (cls.owner, cls.member)), ('b', (cls.owner_b, cls.member_b))):
        keys = {}
        for user in actors:
            row = CounterpartyImport(office_id=user.accountant_profile.office_id, actor=user,
                source_sha256='sha256:'+'0'*64, expires_at=timezone.now()+timedelta(minutes=25))
            seal(row, {'rows': [], 'mappings': []})
            with transaction.atomic(), audit_context(user, 'Συνθετική προεπισκόπηση ορίων'):
                row.save()
            keys[str(user.pk)] = row.pk
        setattr(cls, 'client_imports_'+suffix, keys)


class XlsxContracts(SimpleTestCase):
    def test_maps_supplied_headers_and_retains_unknown_and_unnamed_values(self):
        result = read_workbook(workbook([[1, 'Δοκιμή', 'Πελάτη', '000000123', '00000000001', '', '', 'Σε έλεγχο', 'Κείμενο', 'Χωρίς τίτλο']]))
        row = result['rows'][0]
        self.assertEqual(row['values']['vat_number'], '000000123')
        self.assertEqual(row['values']['main_amka'], '00000000001')
        self.assertIn(['ΚΑΤΑΣΤΑΣΗ 1', 'Σε έλεγχο'], row['extras'])
        self.assertTrue(any(label.endswith('(χωρίς τίτλο)') and value == 'Χωρίς τίτλο' for label, value in row['extras']))

    def test_numeric_identifiers_restore_fixed_width_with_visible_warning(self):
        row = read_workbook(workbook([[1, 'Δοκιμή', 'Πελάτη', 123, 1]]))['rows'][0]
        self.assertEqual((row['values']['vat_number'], row['values']['main_amka']), ('000000123', '00000000001'))
        self.assertEqual(len(row['warnings']), 2)

    def test_formula_cells_are_not_evaluated_or_imported(self):
        with self.assertRaises(XlsxError):
            read_workbook(workbook([['', 'Δοκιμή', '', '000000123']], formula=True))

    def test_duplicate_known_headers_are_rejected(self):
        with self.assertRaises(XlsxError):
            read_workbook(workbook([['Δοκιμή', '000000123', '000000123']], ['ΕΠΩΝΥΜΟ', 'ΑΦΜ', 'Α.Φ.Μ.']))

    def test_no_headers_and_non_excel_content_are_rejected(self):
        for body in (b'plain data', workbook([['nothing']], ['other'])):
            with self.subTest(size=len(body)), self.assertRaises(XlsxError):
                read_workbook(body)

    def test_row_limit_rejects_whole_file_without_truncation(self):
        with self.assertRaises(XlsxError):
            read_workbook(workbook([['', 'Δοκιμή', '', '000000123']] * 251))

    def test_macros_and_external_parts_are_rejected(self):
        for name in ('xl/vbaProject.bin', 'xl/externalLinks/externalLink1.xml'):
            data = io.BytesIO(workbook([['', 'Δοκιμή', '', '000000123']]))
            with zipfile.ZipFile(data, 'a') as z:
                z.writestr(name, 'synthetic')
            with self.assertRaises(XlsxError):
                read_workbook(data.getvalue())


class ImportContracts(ProfileSupport, TestCase):
    def setUp(self):
        self.seed_profile()
        self.foreign_actor = get_user_model().objects.create_user('cr010-foreign', password=secrets.token_urlsafe(32))
        create_accountant_profile(user_id=self.foreign_actor.pk, office_id=self.foreign.pk, role='owner')
        state = state_for(self.member); state.enrolled_at = timezone.now(); state.save(update_fields=['enrolled_at'])
        self.username = secrets.token_urlsafe(16); self.password = secrets.token_urlsafe(32)

    def raw_row(self, **changes):
        values = {'number': '1', 'surname': 'Συνθετικός', 'name': 'Πελάτης', 'afm': '000000777', 'amka': '00000000001',
            'username': self.username, 'password': self.password, 'state': 'Ολοκληρώθηκε δήλωση', 'notes': '<b>Συνθετικό</b>', 'unnamed': 'Πρόσθετο'} | changes
        return list(values.values())

    def stage(self, rows=None):
        with patch('accounting.client_import_services.scan_content', return_value='synthetic-unit-scan'):
            return stage_import(self.member, SimpleUploadedFile('synthetic.xlsx', workbook(rows or [self.raw_row()])))

    def decisions(self, row, action=None, *, replace=False):
        data = open_preview(row)
        return [{'key': r['key'], 'action': action or ('UPDATE' if r['match_id'] else 'CREATE'),
            'kind': r['kind'] or 'INDIVIDUAL', 'replace_credentials': replace} for r in data['rows']]

    def test_upload_is_a_sealed_preview_and_has_no_client_or_financial_writes(self):
        counts = (Entity.objects.count(), CounterpartyNote.objects.count(), Charge.objects.count(), Transaction.objects.count())
        row = self.stage()
        self.assertEqual(counts, (Entity.objects.count(), CounterpartyNote.objects.count(), Charge.objects.count(), Transaction.objects.count()))
        self.assertNotIn(self.password.encode(), bytes(row.payload))
        self.assertEqual(open_preview(row)['rows'][0]['values']['password'], self.password)

    def test_confirm_creates_client_amka_vault_and_unknown_column_note(self):
        row = self.stage(); before = (Charge.objects.count(), Transaction.objects.count(), FinanceAuditEvent.objects.count())
        result, replay = confirm_import(self.member, row.pk, self.decisions(row))
        person = Entity.objects.get(office=self.office, vat_key='000000777')
        self.assertFalse(replay); self.assertTrue(person.is_customer)
        self.assertEqual(person.fiscal_profile.main_amka, '00000000001')
        self.assertEqual(open_sealed(TaxisCredential.objects.get(entity=person)), (self.username, self.password))
        note = CounterpartyNote.objects.get(entity=person)
        self.assertIn('ΚΑΤΑΣΤΑΣΗ 1: Ολοκληρώθηκε δήλωση', note.body)
        self.assertIn('Στήλη J (χωρίς τίτλο): Πρόσθετο', note.body)
        self.assertEqual(note.actor_id, self.member.pk); self.assertTrue(note.subject)
        self.assertEqual(before, (Charge.objects.count(), Transaction.objects.count(), FinanceAuditEvent.objects.count()))
        self.assertEqual((bytes(result.payload), bytes(result.salt)), (b'', b''))

    def test_preview_html_masks_both_credentials_and_escapes_unknown_text(self):
        row = self.stage(); response = self.client_for().get(reverse('counterparty-import-preview', args=[row.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, self.username); self.assertNotContains(response, self.password)
        self.assertContains(response, '&lt;b&gt;Συνθετικό&lt;/b&gt;')
        self.assertNotContains(response, '<b>Συνθετικό</b>')

    def test_existing_afm_is_previewed_and_defaults_to_skip(self):
        self.save(core={'vat_number': '000000777'}, main_amka='00000000002')
        row = self.stage(); response = self.client_for().get(reverse('counterparty-import-preview', args=[row.pk]))
        self.assertContains(response, 'Ενημέρωση υπάρχουσας καρτέλας')
        self.assertContains(response, 'Παράλειψη')
        result, _ = confirm_import(self.member, row.pk, self.decisions(row, 'SKIP'))
        self.assertEqual(result.outcome['skipped'], 1)
        self.person.refresh_from_db(); self.assertEqual(self.person.fiscal_profile.main_amka, '00000000002')

    def test_update_keeps_empty_cells_contacts_and_existing_credentials(self):
        original = self.credentials(); self.save(core={'vat_number': '000000777'}, credentials=original, main_amka='00000000002')
        address = self.person.address
        row = self.stage([self.raw_row(amka='')]); confirm_import(self.member, row.pk, self.decisions(row))
        self.person.refresh_from_db(); self.assertEqual(self.person.address, address)
        self.assertEqual(self.person.fiscal_profile.main_amka, '00000000002')
        self.assertEqual(open_sealed(TaxisCredential.objects.get(entity=self.person)), (original['main_taxis_username'], original['main_taxis_password']))

    def test_credential_replacement_requires_explicit_row_choice(self):
        self.save(core={'vat_number': '000000777'}, credentials=self.credentials())
        row = self.stage(); confirm_import(self.member, row.pk, self.decisions(row, replace=True))
        self.assertEqual(open_sealed(TaxisCredential.objects.get(entity=self.person)), (self.username, self.password))

    def test_invalid_amka_and_repeated_afm_are_visible_and_cannot_be_imported(self):
        for records in ([self.raw_row(amka='123')], [self.raw_row(), self.raw_row()]):
            row = self.stage(records)
            self.assertTrue(all(r['errors'] for r in open_preview(row)['rows']))
            with self.assertRaises(ValidationError):
                confirm_import(self.member, row.pk, self.decisions(row))
            self.assertFalse(Entity.objects.filter(vat_key='000000777').exists())

    def test_changed_client_after_preview_blocks_every_selected_row(self):
        self.save(core={'vat_number': '000000777'})
        row = self.stage([self.raw_row(afm='000000778'), self.raw_row()]); self.save(main_amka='00000000003')
        with self.assertRaises(ValidationError):
            confirm_import(self.member, row.pk, self.decisions(row))
        self.assertFalse(Entity.objects.filter(vat_key='000000778').exists())

    def test_note_write_failure_rolls_back_client_profile_and_credentials(self):
        row = self.stage()
        with patch('accounting.client_import_services.add_note', side_effect=ValidationError('synthetic')):
            with self.assertRaises(ValidationError):
                confirm_import(self.member, row.pk, self.decisions(row))
        self.assertFalse(Entity.objects.filter(vat_key='000000777').exists())
        row.refresh_from_db(); self.assertEqual(row.state, 'PREVIEW')

    def test_retry_same_decisions_does_not_duplicate_notes_or_clients(self):
        row = self.stage(); decisions = self.decisions(row); first, _ = confirm_import(self.member, row.pk, decisions)
        counts = (Entity.objects.count(), CounterpartyNote.objects.count(), TaxisCredential.objects.count())
        second, replay = confirm_import(self.member, row.pk, decisions)
        self.assertEqual(first.pk, second.pk); self.assertTrue(replay)
        self.assertEqual(counts, (Entity.objects.count(), CounterpartyNote.objects.count(), TaxisCredential.objects.count()))
        with self.assertRaises(ValidationError):
            confirm_import(self.member, row.pk, decisions[:-1])

    def test_new_upload_of_identical_completed_file_is_not_imported_again(self):
        row = self.stage(); confirm_import(self.member, row.pk, self.decisions(row))
        with self.assertRaises(ValidationError): self.stage()

    def test_foreign_or_other_author_cannot_read_preview(self):
        row = self.stage()
        with self.assertRaises(Http404): current_preview(self.owner, row.pk)
        with self.assertRaises(Http404): current_preview(self.foreign_actor, row.pk)

    def test_revocation_after_preview_blocks_confirmation(self):
        row = self.stage(); decisions = self.decisions(row)
        AccountantProfile.objects.filter(user=self.member).update(is_active=False)
        with self.assertRaises(PermissionDenied): confirm_import(self.member, row.pk, decisions)
        self.assertFalse(Entity.objects.filter(vat_key='000000777').exists())

    def test_cancel_purges_preview_and_never_creates_client(self):
        row = self.stage(); decisions = self.decisions(row); cancelled = cancel_import(self.member, row.pk)
        self.assertEqual((cancelled.state, bytes(cancelled.payload)), ('CANCELLED', b''))
        with self.assertRaises(ValidationError): confirm_import(self.member, row.pk, decisions)
        self.assertFalse(Entity.objects.filter(vat_key='000000777').exists())

    def test_expired_preview_blocks_read_and_confirm_until_explicit_cancellation(self):
        row = self.stage(); decisions = self.decisions(row)
        with patch('accounting.client_import_services.timezone.now', return_value=row.expires_at+timedelta(seconds=1)):
            with self.assertRaises(ValidationError): confirm_import(self.member, row.pk, decisions)
            with self.assertRaises(ValidationError): current_preview(self.member, row.pk)
        row.refresh_from_db(); self.assertEqual(row.state, 'PREVIEW')
        cancel_import(self.member, row.pk)
        row.refresh_from_db(); self.assertEqual((row.state, bytes(row.payload)), ('CANCELLED', b''))

    def test_long_unknown_column_is_retained_across_multiple_notes(self):
        value = 'Δοκιμή ' * 1000
        row = self.stage([self.raw_row(notes=value)])
        confirm_import(self.member, row.pk, self.decisions(row))
        person = Entity.objects.get(vat_key='000000777')
        bodies = list(CounterpartyNote.objects.filter(entity=person).order_by('created_at', 'pk').values_list('body', flat=True))
        self.assertGreater(len(bodies), 1)
        self.assertIn(value, ''.join(body.removeprefix('Στοιχεία αρχείου:\n').removesuffix('\nΤέλος στοιχείων.') for body in bodies))

    def test_failed_scanner_has_no_preview_or_client_writes(self):
        with override_settings(ATTACHMENT_SCANNER_HOST=''):
            with self.assertRaises(ValidationError): stage_import(self.member, SimpleUploadedFile('sample.xlsx', workbook([self.raw_row()])))
        self.assertFalse(CounterpartyImport.objects.exists())

    def test_final_import_record_is_sql_immutable(self):
        row = self.stage(); confirm_import(self.member, row.pk, self.decisions(row))
        with self.assertRaises(DatabaseError), transaction.atomic(), audit_context(self.member, 'synthetic'):
            CounterpartyImport.objects.filter(pk=row.pk).update(state='PREVIEW')
