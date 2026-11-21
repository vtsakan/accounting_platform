"""Operator-run PG17 and real PDF/CSV reconciliation contracts; synthetic only."""
import csv
import io
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
from pypdf import PdfReader
from django.db import close_old_connections,connection
from django.db.migrations.executor import MigrationExecutor
from .schema_test_support import restore_current_test_schema
from django.test import Client,TestCase,TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from core.locale import format_euro
from . import export_views
from .export_schema import ExportError,Provenance,section
from .export_renderers import csv_text,render_csv,render_pdf
from .export_selectors import build_document
from .finance_services import post_cash,post_transfer
from .membership import change_membership
from .models import CashAccount,Entity,Transaction
from .report_forms import PeriodReportForm
from .settlement_services import release_allocation
from .tests_reports import ReportFixtures
from .tests_finance_posting import DAY


class ExportFixtures(ReportFixtures):
    def setUp(self):
        super().setUp();self.web=self.client_for()

    def export_url(self,kind='period',filetype='csv',entity=None):
        name={'period':'report-export','statement':'client-statement-export','annual':'fees-overview-export'}[kind]
        kwargs={'filetype':filetype}
        if kind=='statement':kwargs['pk']=(entity or self.customer).pk
        return reverse(name,kwargs=kwargs)

    def download(self,kind='period',filetype='csv',**changes):
        values={'start_date':DAY.replace(day=1).isoformat(),'end_date':DAY.isoformat(),'as_of':DAY.isoformat()}|changes
        response=self.web.get(self.export_url(kind,filetype),values,HTTP_ACCEPT_LANGUAGE='en')
        return response

    def csv_rows(self,response):
        self.assertEqual(response.status_code,200)
        return list(csv.DictReader(io.StringIO(response.content.decode('utf-8-sig')),delimiter=';'))

    def pdf(self,response):
        self.assertEqual(response.status_code,200)
        reader=PdfReader(io.BytesIO(response.content),strict=True)
        return reader,'\n'.join(p.extract_text() for p in reader.pages)

    def metric(self,rows,label):return next(r['Ποσό EUR'] for r in rows if r['Μέγεθος']==label)

    def described_cash(self,description):
        return post_cash(self.member,idempotency_key=str(uuid.uuid4()),amount='10.00',transaction_date=DAY,
            transaction_type='INCOME',cash_account=self.account,entity=self.customer,description=description)

    def document(self):
        form=PeriodReportForm({'as_of':DAY.isoformat(),'end_date':DAY.isoformat()},user=self.member)
        return build_document(self.member,form,'period','csv')


class ExportContracts(ExportFixtures,TestCase):
    def test_period_csv_totals_equal_the_same_screen_scope(self):
        self.scenario();screen=self.web.get(reverse('summary-report'),{'as_of':DAY.isoformat(),'end_date':DAY.isoformat()})
        rows=self.csv_rows(self.download())
        self.assertEqual(self.metric(rows,'Λειτουργικές εισπράξεις'),format_euro(screen.context['total_income'],symbol=False))
        self.assertEqual(self.metric(rows,'Ανεξόφλητες χρεώσεις πελατών'),format_euro(screen.context['receivable_remaining'],symbol=False))

    def test_period_pdf_totals_equal_the_same_screen_scope(self):
        self.scenario();_,text=self.pdf(self.download(filetype='pdf'))
        self.assertIn('120,00 €',text);self.assertIn('75,00 €',text);self.assertIn('Οικονομική αναφορά περιόδου',text)

    def test_statement_csv_matches_dated_statement_totals(self):
        self.scenario();expected=self.statement();rows=self.csv_rows(self.download('statement'))
        self.assertEqual(self.metric(rows,'Ανεξόφλητες χρεώσεις πελατών'),format_euro(expected['receivable_remaining'],symbol=False))
        self.assertEqual(self.metric(rows,'Αδιάθετη πίστωση πελατών'),format_euro(expected['customer_credit'],symbol=False))

    def test_statement_pdf_contains_same_debt_credit_and_counterparty(self):
        self.scenario();_,text=self.pdf(self.download('statement','pdf'))
        self.assertIn(self.customer.name,text);self.assertIn('75,00 €',text);self.assertIn('95,00 €',text)

    def test_annual_csv_has_all_twelve_months_and_reconciled_totals(self):
        self.scenario();rows=self.csv_rows(self.download('annual',year=str(DAY.year),month='1',entity=str(self.customer.pk)))
        months=[r for r in rows if r['Ενότητα']=='Δώδεκα μήνες'];self.assertEqual(len(months),12)
        self.assertEqual((months[0]['Καθαρό ποσό EUR'],months[0]['Λειτουργικές εισπράξεις EUR'],months[0]['Ανεξόφλητο EUR']),('100,00','120,00','75,00'))
        annual=next(r for r in rows if r['Ενότητα']=='Σύνολα έτους');whole=next(r for r in rows if r['Μέγεθος']=='Σύνολο καρτέλας')
        self.assertEqual(annual['Ανεξόφλητο EUR'],whole['Ανεξόφλητο EUR'])

    def test_annual_pdf_contains_year_months_and_outside_year_basis(self):
        self.scenario();_,text=self.pdf(self.download('annual','pdf',year=str(DAY.year),month='1'))
        self.assertIn('12/2026',text);self.assertIn('120,00 €',text);self.assertIn('Εκτός έτους',text)

    def test_csv_includes_all_cash_pages_instead_of_only_screen_page(self):
        for _ in range(26):self.cash(amount='1.00')
        rows=self.csv_rows(self.download(page_size='25'))
        cash=[r for r in rows if r['Ενότητα']=='Λειτουργικές κινήσεις'];self.assertEqual(len(cash),26)
        self.assertEqual(self.metric(rows,'Λειτουργικές εισπράξεις'),'26,00')

    def test_export_includes_every_charge_page(self):
        for _ in range(26):self.obligation(agreement=self.second_agreement())
        rows=self.csv_rows(self.download(page_size='25'))
        charges=[r for r in rows if r['Ενότητα'].startswith('Χρεώσεις έως')]
        self.assertEqual(len(charges),26);self.assertEqual(self.metric(rows,'Ανεξόφλητες χρεώσεις πελατών'),'2.600,00')

    def test_page_number_does_not_change_export_scope_or_totals(self):
        for _ in range(26):self.cash(amount='1.00')
        a=self.csv_rows(self.download(page='1'));b=self.csv_rows(self.download(page='2'))
        self.assertEqual([r for r in a if r['Ενότητα']!='Προέλευση'],[r for r in b if r['Ενότητα']!='Προέλευση'])

    def test_description_filter_uses_the_same_cash_queryset_and_balance_basis(self):
        self.described_cash('Επιλεγμένη κίνηση');self.described_cash('Άλλη κίνηση')
        rows=self.csv_rows(self.download(query='Επιλεγμένη'))
        self.assertEqual(self.metric(rows,'Λειτουργικές εισπράξεις'),'10,00')
        self.assertEqual(self.metric(rows,'Αδιάθετη πίστωση πελατών'),'20,00')
        self.assertEqual(len([r for r in rows if r['Ενότητα']=='Λειτουργικές κινήσεις']),1)

    def test_dated_release_preserves_earlier_export_and_later_history(self):
        _,_,allocation=self.scenario();day=DAY+timedelta(days=2)
        release_allocation(self.request(),**self.release_values(allocation,effective_date=day))
        before=self.csv_rows(self.download('statement'));after=self.csv_rows(self.download('statement',as_of=day.isoformat(),end_date=day.isoformat()))
        self.assertEqual(self.metric(before,'Ανεξόφλητες χρεώσεις πελατών'),'75,00')
        self.assertEqual(self.metric(after,'Ανεξόφλητες χρεώσεις πελατών'),'100,00')
        events=[r for r in after if r['Ενότητα'].startswith('Αντιστοιχίσεις και')]
        self.assertEqual([r['Ποσό EUR'] for r in events],['25,00','-25,00'])

    def test_transfer_has_zero_operating_effect_but_reconciles_account_bridge(self):
        post_transfer(self.member,from_account=self.account,to_account=self.other,amount='5.00',transfer_date=DAY,description='Μεταφορά S30',idempotency_key=str(uuid.uuid4()))
        rows=self.csv_rows(self.download(cash_account=str(self.account.pk)))
        self.assertEqual(self.metric(rows,'Λειτουργικές εισπράξεις'),'0,00');self.assertEqual(self.metric(rows,'Καθαρή λειτουργική ροή'),'0,00')
        bridge=next(r for r in rows if r['Ενότητα']=='Συμφωνία πλήρων επιλεγμένων ταμείων')
        self.assertEqual((bridge['Τελικό υπόλοιπο EUR'],bridge['Εξερχόμενα EUR'],bridge['Διαφορά συμφωνίας EUR']),('95,00','5,00','0,00'))

    def test_unknown_opening_remains_unknown_in_csv_and_pdf(self):
        CashAccount.objects.create(office=self.office,name='Άγνωστο ταμείο S30',opening_balance='500.00')
        rows=self.csv_rows(self.download());row=next(r for r in rows if r['Ταμείο']=='Άγνωστο ταμείο S30')
        self.assertEqual(row['Τελικό υπόλοιπο EUR'],'Άγνωστο')
        _,text=self.pdf(self.download(filetype='pdf'));self.assertIn('Άγνωστο',text)

    def test_malformed_filters_return_greek_errors_without_attachment(self):
        for values in ({'start_date':'invalid'},{'year':'invalid'},{'page':'-1'}):
            kind='annual' if 'year' in values else 'period'
            response=self.download(kind,**values);self.assertEqual(response.status_code,400)
            self.assertNotIn('Content-Disposition',response);self.assertContains(response,'Η εξαγωγή δεν ολοκληρώθηκε',status_code=400)

    def test_duplicate_filters_are_denied_instead_of_broadening_scope(self):
        response=self.web.get(self.export_url()+'?as_of=2026-01-15&as_of=2026-01-16')
        self.assertEqual(response.status_code,400);self.assertNotIn('Content-Disposition',response)

    def test_future_asof_is_denied_for_both_formats(self):
        for fmt in ('pdf','csv'):
            response=self.download(filetype=fmt,as_of=(timezone.localdate()+timedelta(days=1)).isoformat())
            self.assertEqual(response.status_code,400)

    def test_foreign_cash_account_is_denied_before_either_export(self):
        for fmt in ('pdf','csv'):
            response=self.download(filetype=fmt,cash_account=str(self.foreign_account.pk));self.assertEqual(response.status_code,404)

    def test_foreign_entity_filter_cannot_enter_an_export(self):
        other=Entity.objects.create(office=self.foreign,name='Ξένη εξαγωγή S30',entity_type='CUSTOMER')
        self.assertEqual(self.download(entity=str(other.pk)).status_code,404)

    def test_foreign_statement_cannot_be_guessed_by_identifier(self):
        other=Entity.objects.create(office=self.foreign,name='Ξένη καρτέλα S30',entity_type='CUSTOMER')
        for fmt in ('pdf','csv'):
            response=self.web.get(self.export_url('statement',fmt,other));self.assertEqual(response.status_code,404)

    def test_statement_export_cannot_switch_to_another_own_counterparty(self):
        self.assertEqual(self.download('statement',entity=str(self.supplier.pk)).status_code,400)

    def test_anonymous_download_requires_authentication(self):
        for fmt in ('pdf','csv'):
            self.assertEqual(Client().get(self.export_url(filetype=fmt)).status_code,302)

    def test_inactive_office_denies_download(self):
        from .models import Office
        Office.objects.filter(pk=self.office.pk).update(is_active=False)
        self.assertEqual(self.download().status_code,403)

    def test_revocation_denies_the_next_export_request(self):
        change_membership(user_id=self.member.pk,office_id=self.office.pk,role='accountant',is_active=False)
        self.assertEqual(self.download().status_code,403)

    def test_revocation_while_serialising_does_not_release_csv(self):
        self.scenario()
        def renderer(document):
            change_membership(user_id=self.member.pk,office_id=self.office.pk,role='accountant',is_active=False)
            return render_csv(document)
        with patch.object(export_views,'render_csv',side_effect=renderer):response=self.download()
        self.assertEqual(response.status_code,403);self.assertNotIn('Content-Disposition',response)

    def test_office_change_before_bytes_are_released_is_denied(self):
        original=export_views.require_capability;calls=[]
        def authority(user,capability):
            calls.append(1)
            return original(user,capability) if len(calls)==1 else SimpleNamespace(office_id=self.foreign.pk)
        with patch.object(export_views,'require_capability',side_effect=authority):response=self.download()
        self.assertEqual(response.status_code,403);self.assertNotIn('Content-Disposition',response)

    def test_post_is_denied_on_every_export_route(self):
        for kind in ('period','statement','annual'):
            for fmt in ('pdf','csv'):self.assertEqual(self.web.post(self.export_url(kind,fmt),{}).status_code,405)

    def test_unrecognised_format_is_404(self):
        self.assertEqual(self.web.get(self.export_url(filetype='html')).status_code,404)

    def test_download_headers_are_private_attachments_with_greek_names(self):
        for fmt,mime in [('pdf','application/pdf'),('csv','text/csv')]:
            response=self.download(filetype=fmt);self.assertEqual(response.status_code,200)
            self.assertTrue(response['Content-Type'].startswith(mime));self.assertIn('attachment;',response['Content-Disposition'])
            self.assertIn('filename*=',response['Content-Disposition']);self.assertIn('no-store',response['Cache-Control'])
            self.assertEqual(response['X-Content-Type-Options'],'nosniff');self.assertEqual(int(response['Content-Length']),len(response.content))
            self.assertEqual(response['Content-Language'],'el')

    def test_every_export_is_read_only_for_financial_records(self):
        self.scenario();before=self.snapshot();counts=(Transaction.objects.count(),self.agreement.charges.count())
        for kind in ('period','statement','annual'):
            for fmt in ('csv','pdf'):self.assertEqual(self.download(kind,fmt).status_code,200)
        self.assertEqual(self.snapshot(),before);self.assertEqual((Transaction.objects.count(),self.agreement.charges.count()),counts)

    def test_pdf_roundtrips_greek_accents_euro_and_embedded_unicode_fonts(self):
        self.described_cash('Άλφα έσοδα ΐ ΰ Ωμέγα S30');reader,text=self.pdf(self.download(filetype='pdf'))
        self.assertIn('Άλφα έσοδα ΐ ΰ Ωμέγα S30',text);self.assertIn('10,00 €',text)
        fonts=[font.get_object() for page in reader.pages for font in page['/Resources']['/Font'].get_object().values()]
        self.assertTrue(any('/ToUnicode' in f and '/FontDescriptor' in f and '/FontFile2' in f['/FontDescriptor'].get_object() for f in fonts))

    def test_csv_preserves_afm_text_and_exact_signed_decimal_types(self):
        entity=Entity.objects.create(office=self.office,name='ΑΦΜ S30',entity_type='CUSTOMER',vat_number='000000601')
        rows=self.csv_rows(self.web.get(self.export_url('statement',entity=entity),{'as_of':DAY.isoformat()}))
        self.assertEqual(next(r['ΑΦΜ'] for r in rows if r['Ενότητα']=='Συναλλασσόμενος'),"'000000601")
        doc=replace(self.document(),sections=(section('Δοκιμή',('label','value','amount'),[('Πρόσημο','Δεκαδικό',Decimal('-10.00'))]),))
        row=list(csv.DictReader(io.StringIO(render_csv(doc).decode('utf-8-sig')),delimiter=';'))[0]
        self.assertEqual(row['Ποσό EUR'],'-10,00')
        with self.assertRaises(ValueError):section('Άκυρο',('amount',),[(1.1,)])

    def test_csv_formula_payloads_are_quoted_literal_text(self):
        base=self.document()
        for text in ('=1+2','+SUM(A1:A2)','-2+3','@SUM(A1)','\t=1','\r=1','\n=1',' \ufeff=1','＝1','＋1','－1','＠1'):
            with self.subTest(text=text):
                doc=replace(base,sections=(section('Δοκιμή κειμένου',('label','value'),[('Περιγραφή',text)]),))
                row=list(csv.DictReader(io.StringIO(render_csv(doc).decode('utf-8-sig')),delimiter=';'))[0]
                self.assertTrue(row['Στοιχείο'].startswith("\t'"));self.assertEqual(row['Στοιχείο'][2:],text)
        self.assertEqual(csv_text('Ελληνικό κείμενο'),'Ελληνικό κείμενο')

    def test_csv_quotes_separators_quotes_and_linebreaks_without_new_cells(self):
        value='Ελληνικά; "πεδίο"\r\nδεύτερη γραμμή'
        doc=replace(self.document(),sections=(section('Κείμενο',('label','value'),[('Περιγραφή',value)]),))
        payload=render_csv(doc);self.assertTrue(payload.startswith(b'\xef\xbb\xbf'))
        rows=list(csv.DictReader(io.StringIO(payload.decode('utf-8-sig')),delimiter=';'))
        self.assertEqual(rows[0]['Στοιχείο'],value);self.assertNotIn(None,rows[0])

    def test_pdf_treats_user_markup_and_remote_images_as_plain_text(self):
        self.described_cash('<img src="https://example.invalid/private"/><b>ΔΟΚΙΜΗ</b>')
        with patch('urllib.request.urlopen',side_effect=AssertionError('No remote assets')) as network:
            _,text=self.pdf(self.download(filetype='pdf'))
        network.assert_not_called();self.assertIn('example.invalid',''.join(text.split()));self.assertIn('<b>ΔΟΚΙΜΗ</b>',''.join(text.split()))

    def test_pdf_paginates_all_rows_with_repeated_greek_headers(self):
        for _ in range(80):self.cash(amount='1.00')
        reader,text=self.pdf(self.download(filetype='pdf'))
        self.assertGreater(len(reader.pages),1);self.assertGreater(text.count('Αναγνωριστικό'),1);self.assertIn('80,00 €',text)

    def test_oversized_scope_is_rejected_without_partial_attachment(self):
        self.scenario()
        with patch('accounting.export_selectors.ROW_LIMITS',{'csv':1,'pdf':1}):
            for fmt in ('csv','pdf'):
                response=self.download(filetype=fmt);self.assertEqual(response.status_code,422);self.assertNotIn('Content-Disposition',response)

    def test_output_byte_limit_is_enforced_without_attachment(self):
        with patch('accounting.export_renderers.MAX_OUTPUT_BYTES',1):response=self.download()
        self.assertEqual(response.status_code,422);self.assertNotIn('Content-Disposition',response)

    def test_posted_exports_and_future_forecast_provenance_remain_separate(self):
        self.scenario();doc=self.document();self.assertEqual(doc.provenance.kind,'posted');self.assertFalse(doc.provenance.rule_version)
        self.assertIn('Καταχωρισμένα οικονομικά στοιχεία',render_csv(doc).decode('utf-8-sig'))
        with self.assertRaises(ValueError):Provenance(kind='estimate')
        future=Provenance(kind='estimate',source_dates=(DAY,),rule_version='S59-υπόδειγμα')
        self.assertIn('Εκτίμηση',future.label);self.assertEqual(self.download(forecast='1').status_code,200)


class ExportSnapshotContracts(ExportFixtures,TransactionTestCase):
    @classmethod
    def setUpClass(cls):
        restore_current_test_schema();super().setUpClass()

    def test_unpaged_rows_and_totals_keep_one_snapshot_during_concurrent_cash(self):
        from .export_selectors import full_rows
        def writer():
            close_old_connections()
            try:return self.cash(amount='10.00').pk
            finally:close_old_connections()
        def collect(result,keys,limit):
            with ThreadPoolExecutor(max_workers=1) as pool:pool.submit(writer).result(timeout=30)
            return full_rows(result,keys,limit)
        with patch('accounting.export_selectors.full_rows',side_effect=collect):doc=self.document()
        rows=self.csv_rows(type('Response',(),{'status_code':200,'content':render_csv(doc)})())
        self.assertEqual(self.metric(rows,'Λειτουργικές εισπράξεις'),'0,00')
        self.assertFalse(any(r['Ενότητα']=='Λειτουργικές κινήσεις' for r in rows));self.assertEqual(Transaction.objects.count(),1)

    def test_concurrent_committed_revocation_blocks_download_after_snapshot(self):
        def revoke():
            close_old_connections()
            try:change_membership(user_id=self.member.pk,office_id=self.office.pk,role='accountant',is_active=False)
            finally:close_old_connections()
        def renderer(doc):
            with ThreadPoolExecutor(max_workers=1) as pool:pool.submit(revoke).result(timeout=30)
            return render_csv(doc)
        with patch.object(export_views,'render_csv',side_effect=renderer):response=self.download()
        self.assertEqual(response.status_code,403);self.assertNotIn('Content-Disposition',response)
