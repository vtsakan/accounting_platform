"""Operator PG17 contracts for explicit GSIS credential copy; no GSIS requests."""
import json
import secrets

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from .auth_policy import state_for
from .counterparty_services import archive_counterparty
from .gsis_services import credentials_for_gsis
from .models import AccountantProfile, Charge, EntityProfileEvent, FinanceAuditEvent, Office, TaxisCredential, Transaction
from .tests_auth_support import staff_client_login
from .tests_entity_profile import ProfileSupport


class GsisContracts(ProfileSupport, TestCase):
    def setUp(self):
        self.seed_profile()

    def url(self, subject='MAIN', person=None):
        return reverse('entity-gsis-credentials', args=[(person or self.person).pk, subject])

    def verified_client(self, user=None, csrf=False):
        user = user or self.member
        state = state_for(user)
        state.enrolled_at = timezone.now()
        state.save(update_fields=['enrolled_at'])
        return self.client_for(user, csrf=csrf)  # Actual fixture TOTP verification, not force-verified flags.

    def archived(self):
        self.person.refresh_from_db()
        archive_counterparty(self.member, self.person.pk, version=self.person.record_version, archive=True)

    def test_main_saved_pair_is_returned_only_by_explicit_post(self):
        values = self.credentials(); self.save(credentials=values)
        response = self.verified_client().post(self.url())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'entity_id':self.person.pk, 'subject':'MAIN',
            'username':values['main_taxis_username'], 'password':values['main_taxis_password'], 'stored':True})

    def test_spouse_has_a_separate_pair_and_never_receives_primary_credentials(self):
        main, spouse = self.credentials(), self.credentials('spouse')
        self.save(**self.spouse(), credentials=main|spouse)
        client = self.verified_client()
        self.assertEqual(client.post(self.url('SPOUSE')).json()['password'], spouse['spouse_taxis_password'])
        self.assertEqual(client.post(self.url()).json()['password'], main['main_taxis_password'])

    def test_absent_main_credentials_return_two_blank_fields(self):
        response = self.verified_client().post(self.url())
        self.assertEqual(response.status_code, 200)
        self.assertEqual((response.json()['username'], response.json()['password'], response.json()['stored']), ('','',False))
        self.assertFalse(EntityProfileEvent.objects.filter(action='REVEAL').exists())

    def test_missing_spouse_pair_stays_blank_even_when_main_pair_exists(self):
        self.save(credentials=self.credentials())
        response = self.verified_client().post(self.url('SPOUSE'))
        self.assertEqual((response.json()['username'], response.json()['password']), ('',''))
        self.assertFalse(EntityProfileEvent.objects.filter(action='REVEAL').exists())

    def test_owner_and_active_accountant_both_have_access(self):
        self.save(credentials=self.credentials())
        for user in (self.owner, self.member):
            self.assertEqual(self.verified_client(user).post(self.url()).status_code, 200)
        self.assertEqual(set(EntityProfileEvent.objects.filter(action='REVEAL').values_list('actor_id',flat=True)),
            {self.owner.pk,self.member.pk})

    def test_get_and_head_do_not_reveal_or_audit_credentials(self):
        self.save(credentials=self.credentials()); client = self.verified_client()
        for method in (client.get, client.head):
            response = method(self.url())
            self.assertEqual(response.status_code, 405)
            self.assertIn('no-store', response['Cache-Control'])
        self.assertFalse(EntityProfileEvent.objects.filter(action='REVEAL').exists())

    def test_anonymous_post_is_redirected_without_reveal(self):
        self.save(credentials=self.credentials())
        self.assertEqual(Client().post(self.url()).status_code, 302)
        self.assertFalse(EntityProfileEvent.objects.filter(action='REVEAL').exists())

    def test_accountant_without_verified_mfa_is_sent_to_mfa(self):
        self.save(credentials=self.credentials()); client = Client()
        staff_client_login(client, self.member)
        response = client.post(self.url())
        self.assertEqual(response.status_code, 302)
        self.assertIn('/auth/mfa/', response['Location'])
        self.assertFalse(EntityProfileEvent.objects.filter(action='REVEAL').exists())

    def test_missing_csrf_after_actual_mfa_is_denied_without_reveal(self):
        self.save(credentials=self.credentials()); client = self.verified_client(csrf=True)
        self.assertEqual(client.post(self.url()).status_code, 403)
        self.assertFalse(EntityProfileEvent.objects.filter(action='REVEAL').exists())

    def test_valid_csrf_after_actual_mfa_can_reveal(self):
        self.save(credentials=self.credentials()); client = self.verified_client(csrf=True)
        response = client.post(self.url(), {'csrfmiddlewaretoken':client.cookies[settings.CSRF_COOKIE_NAME].value})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(EntityProfileEvent.objects.filter(action='REVEAL').count(), 1)

    def test_foreign_entity_is_not_found_and_does_not_create_audit(self):
        response = self.verified_client().post(self.url(person=self.foreign_person))
        self.assertEqual(response.status_code, 404)
        self.assertFalse(EntityProfileEvent.objects.filter(action='REVEAL').exists())

    def test_subject_tampering_is_not_found(self):
        client = self.verified_client()
        for subject in ('main','OTHER','spouse'):
            self.assertEqual(client.post(self.url(subject)).status_code, 404)
        self.assertFalse(EntityProfileEvent.objects.filter(action='REVEAL').exists())

    def test_posted_foreign_identifiers_do_not_override_selected_route(self):
        values = self.credentials(); self.save(credentials=values)
        response = self.verified_client().post(self.url(), {'entity_id':self.foreign_person.pk,
            'office_id':self.foreign.pk, 'subject':'SPOUSE'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['entity_id'], self.person.pk)
        self.assertEqual(response.json()['username'], values['main_taxis_username'])

    def test_revocation_after_login_blocks_credential_access(self):
        self.save(credentials=self.credentials()); client = self.verified_client()
        AccountantProfile.objects.filter(user=self.member).update(is_active=False)
        self.assertEqual(client.post(self.url()).status_code, 403)
        self.assertFalse(EntityProfileEvent.objects.filter(action='REVEAL').exists())

    def test_disabled_office_blocks_even_an_existing_owner_session(self):
        self.save(credentials=self.credentials()); client = self.verified_client(self.owner)
        Office.objects.filter(pk=self.office.pk).update(is_active=False)
        self.assertEqual(client.post(self.url()).status_code, 403)
        self.assertFalse(EntityProfileEvent.objects.filter(action='REVEAL').exists())

    def test_archived_client_cannot_reveal_or_fall_back_to_other_credentials(self):
        self.save(credentials=self.credentials()); self.archived()
        self.assertEqual(self.verified_client().post(self.url()).status_code, 409)
        self.assertFalse(EntityProfileEvent.objects.filter(action='REVEAL').exists())

    def test_success_has_private_no_store_and_no_referrer_headers(self):
        self.save(credentials=self.credentials()); response = self.verified_client().post(self.url())
        self.assertIn('no-store', response['Cache-Control']); self.assertIn('private', response['Cache-Control'])
        self.assertEqual(response['Pragma'], 'no-cache'); self.assertEqual(response['Referrer-Policy'], 'no-referrer')
        self.assertEqual(response['X-Content-Type-Options'], 'nosniff')
        self.assertTrue(response['Content-Type'].startswith('application/json'))

    def test_reveal_event_has_actor_time_subject_and_no_credential_values(self):
        values = self.credentials(); self.save(credentials=values); start = timezone.now()
        self.verified_client().post(self.url()); event = EntityProfileEvent.objects.get(action='REVEAL')
        self.assertEqual(event.actor_id, self.member.pk); self.assertEqual(event.actor_label, self.member.username)
        self.assertEqual(event.subject, 'MAIN'); self.assertGreaterEqual(event.occurred_at, start)
        self.assertEqual(event.changed_fields, ['MAIN'])
        body = json.dumps({'fields':event.changed_fields,'subject':event.subject,'actor':event.actor_label})
        for value in values.values(): self.assertNotIn(value, body)

    def test_copy_read_does_not_change_sealed_bytes_or_financial_rows(self):
        self.save(credentials=self.credentials())
        sealed = list(TaxisCredential.objects.values())
        financial = {model._meta.label:list(model.objects.values()) for model in (Charge, Transaction, FinanceAuditEvent)}
        self.verified_client().post(self.url())
        self.assertEqual(list(TaxisCredential.objects.values()), sealed)
        self.assertEqual({model._meta.label:list(model.objects.values()) for model in (Charge, Transaction, FinanceAuditEvent)}, financial)

    def test_customer_card_has_both_buttons_without_any_plaintext_secret(self):
        values = self.credentials()|self.credentials('spouse'); self.save(**self.spouse(), credentials=values)
        response = self.verified_client().get(reverse('entity-detail', args=[self.person.pk]))
        self.assertContains(response, 'Σύνδεση GSIS — Πελάτης'); self.assertContains(response, 'Σύνδεση GSIS — Σύζυγος')
        self.assertContains(response, 'Συμφωνίες'); self.assertContains(response, 'Σημειώσεις καρτέλας')
        self.assertContains(response, 'Εργασίες πελάτη'); self.assertContains(response, 'Συνημμένα')
        for value in values.values(): self.assertNotContains(response, value)
        self.assertFalse(EntityProfileEvent.objects.filter(action='REVEAL').exists())

    def test_editor_has_both_buttons_and_keeps_saved_values_out_of_get_html(self):
        values = self.credentials(); self.save(credentials=values)
        response = self.verified_client().get(reverse('edit-entity', args=[self.person.pk]))
        self.assertContains(response, 'Σύνδεση GSIS — Πελάτης'); self.assertContains(response, 'Σύνδεση GSIS — Σύζυγος')
        for value in values.values(): self.assertNotContains(response, value)

    def test_archived_card_keeps_history_but_hides_launch_buttons(self):
        self.save(credentials=self.credentials()); self.archived()
        response = self.verified_client().get(reverse('entity-detail', args=[self.person.pk]))
        self.assertNotContains(response, 'data-gsis-launch'); self.assertContains(response, 'Συμφωνίες')

    def test_credential_markup_is_json_data_and_never_rendered_as_html(self):
        values = self.credentials(); values['main_taxis_username'] = '<script>'+secrets.token_urlsafe(8)+'</script>'
        self.save(credentials=values); response = self.verified_client().post(self.url())
        self.assertTrue(response['Content-Type'].startswith('application/json'))
        self.assertEqual(response.json()['username'], values['main_taxis_username'])
        self.assertEqual(response['X-Content-Type-Options'], 'nosniff')

    def test_service_also_rechecks_scope_independently_of_http(self):
        self.save(credentials=self.credentials())
        with self.assertRaises(Http404): credentials_for_gsis(self.member, self.foreign_person.pk, 'MAIN')
        AccountantProfile.objects.filter(user=self.member).update(is_active=False)
        with self.assertRaises(PermissionDenied): credentials_for_gsis(self.member, self.person.pk, 'MAIN')
