"""CR008 isolated operator contracts; actual antivirus is a separate native gate."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
import hashlib
import io
import json
import secrets
import struct
import subprocess
import uuid
from unittest.mock import patch

from django.conf import settings
from django.core.exceptions import PermissionDenied,ValidationError,RequestDataTooBig
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError,connection,transaction,close_old_connections
from django.test import TestCase,SimpleTestCase,TransactionTestCase,Client,override_settings
from django.urls import reverse

from core.attachment_crypto import unseal
from core.attachment_upload import BoundedAttachmentUploadHandler
from .attachment_models import AttachmentCategory,ClientAttachment,AttachmentEvent,MAX_FILE_BYTES
from .attachment_selectors import attachment_rows,attachments_installed
from .attachment_services import (save_category,upload_attachment,edit_attachment,remove_attachment,
    download_attachment,attachment_context)
from .attachment_validation import upload_bytes,inspect_content,scan_content
from .counterparty_retirement_services import delete_counterparty
from .counterparty_services import archive_counterparty
from .membership import create_accountant_profile
from .models import Entity,AccountantProfile,Transaction,Charge,FinanceAuditEvent
from .schema_test_support import restore_current_test_schema
from .tests_auth_support import staff_client_login
from .tests_finance_posting import Fixtures
from .tests_attachment_support import file,pdf_bytes,docx_bytes,doc_bytes,image_bytes,SCANNER


class AttachmentSupport(Fixtures):
    @classmethod
    def setUpClass(cls):restore_current_test_schema();super().setUpClass()

    def setup_files(self):
        self.seed()
        pdf_bytes()
        self.document_category=save_category(self.owner,name='Ταυτότητες')
        self.foreign_owner=type(self.owner).objects.create_user('cr008-foreign',password=secrets.token_urlsafe(32))
        create_accountant_profile(user_id=self.foreign_owner.pk,office_id=self.foreign.pk,role='owner')
        self.foreign_category=save_category(self.foreign_owner,name='ΞΕΝΟΣ ΧΑΡΑΚΤΗΡΙΣΜΟΣ')
        self.scanner=patch('accounting.attachment_services.scan_content',return_value=SCANNER);self.scanner.start();self.addCleanup(self.scanner.stop)
        self.inspector=patch('accounting.attachment_services.inspect_content',return_value='application/pdf');self.inspector.start();self.addCleanup(self.inspector.stop)

    def upload(self,**changes):
        values={'category_id':self.document_category.pk,'description':'Ελεύθερη περιγραφή',
            'upload':file(),'request_key':uuid.uuid4()}|changes
        return upload_attachment(self.member,self.customer.pk,**values)

    def client_for(self,user=None,csrf=False):
        client=Client(enforce_csrf_checks=csrf)
        if csrf:
            client.get('/login/');client.defaults['HTTP_X_CSRFTOKEN']=client.cookies[settings.CSRF_COOKIE_NAME].value
        try:staff_client_login(client,user or self.member)
        finally:client.defaults.pop('HTTP_X_CSRFTOKEN',None)
        return client


class AttachmentFormatContracts(SimpleTestCase):
    def test_pdf_doc_docx_and_image_structures_pass_isolated_inspection(self):
        for extension,data in [('pdf',pdf_bytes()),('docx',docx_bytes()),('doc',doc_bytes()),
            ('png',image_bytes()),('jpg',image_bytes('JPEG')),('gif',image_bytes('GIF'))]:
            with self.subTest(extension=extension):self.assertTrue(inspect_content(extension,data))

    def test_renamed_text_and_html_are_not_documents(self):
        for extension in ('pdf','doc','docx','png'):
            with self.subTest(extension=extension),self.assertRaises(ValidationError):inspect_content(extension,b'<html>unsafe</html>')

    def test_size_empty_and_extension_are_bounded(self):
        for upload in (file(body=b''),file('x.svg',b'<svg/>'),file(body=b'x'*(MAX_FILE_BYTES+1))):
            with self.assertRaises(ValidationError):upload_bytes(upload)

    def test_client_declared_mime_does_not_decide_content_type(self):
        uploaded=SimpleUploadedFile('test.pdf',pdf_bytes(),content_type='image/png')
        name,extension,body,digest=upload_bytes(uploaded)
        self.assertEqual(inspect_content(extension,body),'application/pdf');self.assertEqual(digest,hashlib.sha256(body).hexdigest())

    def test_bounded_upload_handler_rejects_before_more_temporary_bytes(self):
        handler=BoundedAttachmentUploadHandler()
        handler.new_file('file','x.pdf','application/pdf',None)
        handler.received=MAX_FILE_BYTES
        with self.assertRaises(RequestDataTooBig):handler.receive_data_chunk(b'x',MAX_FILE_BYTES)

    def test_scanner_unconfigured_and_network_failure_are_not_clean(self):
        with override_settings(ATTACHMENT_SCANNER_HOST=''):
            with self.assertRaises(ValidationError):scan_content(b'anything')
        with override_settings(ATTACHMENT_SCANNER_HOST='scanner'),patch('socket.create_connection',side_effect=OSError):
            with self.assertRaises(ValidationError):scan_content(b'anything')

    def test_docx_macro_and_external_template_are_rejected(self):
        import zipfile
        for member,body in [('word/vbaProject.bin',b'macro'),('word/_rels/document.xml.rels',b'<Relationships><Relationship TargetMode="External" Type="template" Target="https://example.invalid"/></Relationships>')]:
            stream=io.BytesIO(docx_bytes())
            with zipfile.ZipFile(stream,'a') as archive:archive.writestr(member,body)
            with self.assertRaises(ValidationError):inspect_content('docx',stream.getvalue())


class AttachmentWriteContracts(AttachmentSupport,TestCase):
    def setUp(self):self.setup_files()

    def test_upload_is_sealed_attributed_and_audited(self):
        start=datetime.now(timezone.utc);row,replay=self.upload()
        self.assertFalse(replay);self.assertNotIn(pdf_bytes(),bytes(row.payload));self.assertEqual(unseal(row),pdf_bytes())
        self.assertEqual(row.uploader_label,self.member.username);self.assertGreaterEqual(row.created_at,start)
        self.assertEqual(AttachmentEvent.objects.get(attachment=row).action,'UPLOAD')

    def test_repeated_same_submission_returns_one_file_and_one_event(self):
        nonce=uuid.uuid4();first,_=self.upload(request_key=nonce);second,replay=self.upload(request_key=nonce)
        self.assertEqual(first.pk,second.pk);self.assertTrue(replay)
        self.assertEqual(ClientAttachment.objects.count(),1);self.assertEqual(AttachmentEvent.objects.filter(attachment=first).count(),1)

    def test_changed_description_under_same_nonce_is_rejected(self):
        nonce=uuid.uuid4();row,_=self.upload(request_key=nonce)
        with self.assertRaises(ValidationError):self.upload(request_key=nonce,description='Διαφορετικό')
        self.assertEqual(ClientAttachment.objects.get(pk=row.pk).description,'Ελεύθερη περιγραφή')

    def test_foreign_category_is_rejected_before_scanning(self):
        with self.assertRaises(ValidationError):self.upload(category_id=self.foreign_category.pk)
        self.assertFalse(ClientAttachment.objects.exists())

    def test_revoked_membership_blocks_upload(self):
        AccountantProfile.objects.filter(user=self.member).update(is_active=False)
        with self.assertRaises(PermissionDenied):self.upload()
        self.assertFalse(ClientAttachment.objects.exists())

    def test_revoked_membership_blocks_an_existing_file_download(self):
        row,_=self.upload();AccountantProfile.objects.filter(user=self.member).update(is_active=False)
        with self.assertRaises(PermissionDenied):download_attachment(self.member,self.customer.pk,row.pk)
        self.assertFalse(AttachmentEvent.objects.filter(action='DOWNLOAD').exists())

    def test_revocation_during_scanning_is_rechecked(self):
        def revoke(body):
            AccountantProfile.objects.filter(user=self.member).update(is_active=False);return SCANNER
        with patch('accounting.attachment_services.scan_content',side_effect=revoke):
            with self.assertRaises(PermissionDenied):self.upload()
        self.assertFalse(ClientAttachment.objects.exists())

    def test_scanner_rejection_and_failure_leave_no_database_bytes(self):
        for message in ('Απόρριψη αρχείου','Ο έλεγχος δεν είναι διαθέσιμος'):
            with patch('accounting.attachment_services.scan_content',side_effect=ValidationError(message)):
                with self.assertRaises(ValidationError):self.upload()
            self.assertFalse(ClientAttachment.objects.exists())

    def test_upload_to_archived_client_is_denied(self):
        person=Entity.objects.create(office=self.office,name='ΑΡΧΕΙΟΘΕΤΗΜΕΝΟΣ',entity_type='CUSTOMER')
        archive_counterparty(self.owner,person.pk,version=person.record_version)
        with self.assertRaises(ValidationError):upload_attachment(self.member,person.pk,category_id=self.document_category.pk,
            description='',upload=file(),request_key=uuid.uuid4())

    def test_reclassification_keeps_exact_sealed_bytes(self):
        row,_=self.upload();before=(bytes(row.payload),bytes(row.salt),bytes(row.nonce),row.content_sha256)
        category=save_category(self.owner,name='Δηλώσεις')
        edit_attachment(self.member,self.customer.pk,row.pk,category_id=category.pk,description='Νέα περιγραφή',version=0)
        row.refresh_from_db();self.assertEqual((bytes(row.payload),bytes(row.salt),bytes(row.nonce),row.content_sha256),before)
        self.assertEqual(row.category_id,category.pk);self.assertEqual(row.record_version,1)

    def test_stale_reclassification_does_not_overwrite(self):
        row,_=self.upload();edit_attachment(self.member,self.customer.pk,row.pk,category_id=row.category_id,description='Νέα',version=0)
        with self.assertRaises(ValidationError):edit_attachment(self.member,self.customer.pk,row.pk,category_id=row.category_id,description='Παλιά',version=0)
        self.assertEqual(ClientAttachment.objects.get(pk=row.pk).description,'Νέα')

    def test_non_owner_cannot_remove_or_manage_common_categories(self):
        row,_=self.upload()
        with self.assertRaises(PermissionDenied):remove_attachment(self.member,self.customer.pk,row.pk,version=0,confirmed=True)
        with self.assertRaises(PermissionDenied):save_category(self.member,name='Όχι')
        self.assertFalse(ClientAttachment.objects.get(pk=row.pk).purged)

    def test_owner_removal_erases_payload_and_private_metadata(self):
        row,_=self.upload();remove_attachment(self.owner,self.customer.pk,row.pk,version=0,confirmed=True);row.refresh_from_db()
        self.assertTrue(row.purged);self.assertEqual(bytes(row.payload),b'');self.assertEqual(row.original_name,'')
        self.assertEqual(row.description,'');self.assertIsNone(row.category_id)
        self.assertEqual(AttachmentEvent.objects.filter(attachment=row,action='REMOVE').count(),1)

    def test_owner_removal_requires_explicit_confirmation_and_current_version(self):
        row,_=self.upload()
        for version,confirmed in ((0,False),(1,True)):
            with self.assertRaises(ValidationError):remove_attachment(self.owner,self.customer.pk,row.pk,version=version,confirmed=confirmed)
        self.assertFalse(ClientAttachment.objects.get(pk=row.pk).purged)

    def test_financial_rows_and_balances_are_unchanged(self):
        before={m._meta.label:list(m.objects.values()) for m in (Transaction,Charge,FinanceAuditEvent)}
        row,_=self.upload();download_attachment(self.member,self.customer.pk,row.pk)
        self.assertEqual({m._meta.label:list(m.objects.values()) for m in (Transaction,Charge,FinanceAuditEvent)},before)

    def test_ciphertext_cannot_be_copied_to_another_identity(self):
        row,_=self.upload();row.entity_id=self.supplier.pk
        with self.assertRaises(ValidationError):unseal(row)

    def test_raw_update_and_audit_mutation_are_denied(self):
        row,_=self.upload()
        with self.assertRaises(IntegrityError),transaction.atomic():ClientAttachment.objects.filter(pk=row.pk).update(description='Παράκαμψη')
        with self.assertRaises(IntegrityError),transaction.atomic():AttachmentEvent.objects.filter(attachment=row).update(action='EDIT')

    def test_inactive_category_cannot_receive_new_uploads(self):
        category=save_category(self.owner,category_id=self.document_category.pk,name='Ταυτότητες',is_active=False,version=0)
        with self.assertRaises(ValidationError):self.upload()
        self.assertFalse(category.is_active)

    def test_duplicate_category_name_and_stale_version_are_rejected(self):
        with self.assertRaises(ValidationError):save_category(self.owner,name='ΤΑΥΤΌΤΗΤΕΣ')
        save_category(self.owner,category_id=self.document_category.pk,name='Νέος χαρακτηρισμός',version=0)
        with self.assertRaises(ValidationError):save_category(self.owner,category_id=self.document_category.pk,name='Παλαιός',version=0)

    def test_owner_client_deletion_also_erases_attached_files(self):
        person=Entity.objects.create(office=self.office,name='ΠΕΛΑΤΗΣ ΓΙΑ ΔΙΑΓΡΑΦΗ',entity_type='CUSTOMER')
        row,_=upload_attachment(self.member,person.pk,category_id=self.document_category.pk,description='Προσωπική',upload=file(),request_key=uuid.uuid4())
        archive_counterparty(self.owner,person.pk,version=person.record_version);person.refresh_from_db()
        delete_counterparty(self.owner,person.pk,version=person.record_version,confirmed=True);row.refresh_from_db()
        self.assertTrue(row.purged);self.assertEqual(bytes(row.payload),b'');self.assertEqual(row.description,'')

    def test_metadata_list_does_not_load_sealed_payloads(self):
        row,_=self.upload();listed=attachment_rows(self.member,self.customer).get(pk=row.pk)
        self.assertIn('payload',listed.get_deferred_fields());self.assertIn('salt',listed.get_deferred_fields())


class AttachmentHTTPContracts(AttachmentSupport,TestCase):
    def setUp(self):self.setup_files()

    def test_card_shows_classification_description_uploader_and_upload_action(self):
        row,_=self.upload();response=self.client_for().get(reverse('entity-detail',args=[self.customer.pk]))
        self.assertEqual(response.status_code,200);self.assertContains(response,'Συνημμένα')
        self.assertContains(response,'Ταυτότητες');self.assertContains(response,'Ελεύθερη περιγραφή');self.assertContains(response,self.member.username)

    def test_upload_form_only_contains_active_own_categories(self):
        response=self.client_for().get(reverse('attachment-upload',args=[self.customer.pk]))
        self.assertContains(response,'Ταυτότητες');self.assertNotContains(response,self.foreign_category.name)
        self.assertContains(response,'multipart/form-data')

    def test_http_upload_defaults_are_not_client_controlled(self):
        response=self.client_for().post(reverse('attachment-upload',args=[self.customer.pk]),{
            'category':self.document_category.pk,'description':'Δοκιμή','request_key':uuid.uuid4(),'file':file(),
            'office_id':self.foreign.pk,'uploaded_by':self.owner.pk,'uploader_label':'Ψεύτικος'})
        self.assertEqual(response.status_code,302);row=ClientAttachment.objects.get()
        self.assertEqual(row.office_id,self.office.pk);self.assertEqual(row.uploaded_by_id,self.member.pk)

    def test_foreign_client_upload_form_is_not_found(self):
        person=Entity.objects.create(office=self.foreign,name='ΞΕΝΟΣ',entity_type='CUSTOMER')
        self.assertEqual(self.client_for().get(reverse('attachment-upload',args=[person.pk])).status_code,404)

    def test_authenticated_download_returns_original_bytes_as_private_attachment(self):
        row,_=self.upload();response=self.client_for().post(reverse('attachment-download',args=[self.customer.pk,row.pk]))
        self.assertEqual(response.status_code,200);self.assertEqual(b''.join(response.streaming_content),pdf_bytes())
        self.assertIn('attachment',response['Content-Disposition']);self.assertIn('no-store',response['Cache-Control'])
        self.assertEqual(response['X-Content-Type-Options'],'nosniff');self.assertEqual(response['Content-Type'],'application/octet-stream')

    def test_download_get_is_read_only_and_requires_a_post(self):
        row,_=self.upload();response=self.client_for().get(reverse('attachment-download',args=[self.customer.pk,row.pk]))
        self.assertEqual(response.status_code,405);self.assertFalse(AttachmentEvent.objects.filter(action='DOWNLOAD').exists())

    def test_guessed_file_uuid_and_wrong_client_cannot_download(self):
        row,_=self.upload();client=self.client_for()
        self.assertEqual(client.post(reverse('attachment-download',args=[self.customer.pk,uuid.uuid4()])).status_code,404)
        self.assertEqual(client.post(reverse('attachment-download',args=[self.supplier.pk,row.pk])).status_code,404)

    def test_foreign_office_cannot_download_even_known_file_uuid(self):
        row,_=self.upload()
        response=self.client_for(self.foreign_owner).post(reverse('attachment-download',args=[self.customer.pk,row.pk]))
        self.assertEqual(response.status_code,404)

    def test_missing_csrf_cannot_upload_or_remove(self):
        row,_=self.upload();client=self.client_for(self.owner,csrf=True)
        for name,args in [('attachment-upload',[self.customer.pk]),('attachment-remove',[self.customer.pk,row.pk])]:
            self.assertEqual(client.post(reverse(name,args=args),{'category':self.document_category.pk,'file':file()}).status_code,403)
        self.assertFalse(ClientAttachment.objects.get(pk=row.pk).purged)

    def test_metadata_and_description_are_escaped(self):
        row,_=self.upload(description='<script>alert(1)</script>')
        response=self.client_for().get(reverse('entity-detail',args=[self.customer.pk]))
        self.assertNotContains(response,'<script>alert(1)</script>');self.assertContains(response,'&lt;script&gt;')

    def test_archived_card_retains_download_and_hides_upload(self):
        person=Entity.objects.create(office=self.office,name='ΙΣΤΟΡΙΚΟ',entity_type='CUSTOMER')
        row,_=upload_attachment(self.member,person.pk,category_id=self.document_category.pk,description='',upload=file(),request_key=uuid.uuid4())
        archive_counterparty(self.owner,person.pk,version=person.record_version)
        response=self.client_for().get(reverse('entity-detail',args=[person.pk]))
        self.assertContains(response,'Δοκιμή.pdf');self.assertNotContains(response,reverse('attachment-upload',args=[person.pk]))
        response=self.client_for().post(reverse('attachment-download',args=[person.pk,row.pk]))
        self.assertEqual(response.status_code,200);response.close()

    def test_client_filters_by_category_and_description(self):
        self.upload(description='Αναγνωριστικό φίλτρου')
        response=self.client_for().get(reverse('entity-detail',args=[self.customer.pk]),{'attachment_q':'ανύπαρκτο'})
        self.assertNotContains(response,'Δοκιμή.pdf')
        response=self.client_for().get(reverse('entity-detail',args=[self.customer.pk]),{'attachment_category':str(self.document_category.pk)})
        self.assertContains(response,'Αναγνωριστικό φίλτρου')

    def test_removal_route_is_owner_only(self):
        row,_=self.upload();url=reverse('attachment-remove',args=[self.customer.pk,row.pk])
        self.assertEqual(self.client_for().get(url).status_code,403)
        self.assertEqual(self.client_for(self.owner).get(url).status_code,200)

    def test_rejected_post_renders_greek_field_error_without_internal_scanner_data(self):
        with patch('accounting.attachment_services.scan_content',side_effect=ValidationError({'file':'Το αρχείο απορρίφθηκε από τον έλεγχο ασφαλείας.'})):
            response=self.client_for().post(reverse('attachment-upload',args=[self.customer.pk]),{'category':self.document_category.pk,
                'description':'','request_key':uuid.uuid4(),'file':file()})
        self.assertEqual(response.status_code,200);self.assertContains(response,'Το αρχείο απορρίφθηκε')
        self.assertFalse(ClientAttachment.objects.exists())


class AttachmentConcurrencyContracts(AttachmentSupport,TransactionTestCase):
    def setUp(self):self.setup_files()

    def test_simultaneous_duplicate_uploads_create_one_file(self):
        user_id=self.member.pk;entity_id=self.customer.pk;category_id=self.document_category.pk;nonce=uuid.uuid4()
        def worker():
            close_old_connections()
            try:
                user=type(self.member).objects.get(pk=user_id)
                return upload_attachment(user,entity_id,category_id=category_id,description='',upload=file(),request_key=nonce)[0].pk
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:keys=list(pool.map(lambda _:worker(),range(2)))
        self.assertEqual(keys[0],keys[1]);self.assertEqual(ClientAttachment.objects.count(),1)

    def test_tampered_ciphertext_fails_before_a_download_event(self):
        row,_=self.upload();row.payload=bytes(row.payload)[:-1]+bytes([bytes(row.payload)[-1]^1])
        with self.assertRaises(ValidationError):unseal(row)
        self.assertFalse(AttachmentEvent.objects.filter(action='DOWNLOAD').exists())

    def test_partial_attachment_schema_fails_closed(self):
        with connection.cursor() as cursor:cursor.execute('ALTER TABLE accounting_clientattachment DISABLE TRIGGER cr008_attachment_guard')
        try:
            with self.assertRaises(RuntimeError):attachments_installed()
        finally:
            with connection.cursor() as cursor:cursor.execute('ALTER TABLE accounting_clientattachment ENABLE TRIGGER cr008_attachment_guard')
        self.assertTrue(attachments_installed())
