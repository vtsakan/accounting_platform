"""Operator-only synthetic probe, mounted read-only outside the application image."""
import io
import json
import os
from pathlib import Path
import re
import sys
import time

sys.path.insert(0, '/app')
from r1_gate import require, profile, performance_result


def guard(*, empty=False):
    """No supplied DSN, arbitrary SQL dump or existing environment is accepted."""
    nonce = os.environ.get('S31_VERIFY_ID', '')
    require(re.fullmatch(r'[0-9a-f]{20}', nonce) is not None, 'isolated_nonce_required')
    name = os.environ.get('DB_NAME', '')
    require(name in {f's31_{nonce}_{suffix}' for suffix in ('base', 'candidate', 'rollback', 'restored')}, 'isolated_database_required')
    require(os.environ.get('DB_USER') == 's31_app' and os.environ.get('DB_HOST') in {'db', 'restore_db'}, 'restricted_local_database_required')
    require(os.environ.get('DJANGO_SETTINGS_MODULE') == 'core.settings.production', 'production_settings_required')
    import django
    django.setup()
    from django.db import connection
    with connection.cursor() as cursor:
        cursor.execute('SELECT current_database(), current_user, rolsuper, rolcreatedb, rolcreaterole FROM pg_roles WHERE rolname=current_user')
        require(cursor.fetchone() == (name, 's31_app', False, False, False), 'restricted_role_identity_mismatch')
        require(connection.vendor == 'postgresql' and connection.pg_version == 170011, 'pinned_pg17_11_required')
        if empty:
            from accounting.models import Office
            from django.contrib.auth import get_user_model
            require(not Office.objects.exists() and not get_user_model().objects.exists(), 'seed_refuses_existing_people_or_offices')
            cursor.execute('CREATE SCHEMA s31_control')
            cursor.execute('CREATE TABLE s31_control.identity (nonce text NOT NULL)')
            cursor.execute('INSERT INTO s31_control.identity VALUES (%s)', [nonce])
        else:
            cursor.execute('SELECT nonce FROM s31_control.identity')
            require(cursor.fetchall() == [(nonce,)], 'database_ownership_marker_mismatch')
    media = Path('/app/media')
    require(not media.exists() or not any(media.iterdir()), 'R1_rehearsal_requires_empty_media_S38_pending')


def client_for(user):
    from django.test import Client
    from accounting.tests_auth_support import staff_client_login
    client = Client(HTTP_HOST='s31.example.invalid', HTTP_X_FORWARDED_PROTO='https', HTTP_ACCEPT_LANGUAGE='en')
    staff_client_login(client, user)
    return client


def fixture():
    from django.contrib.auth import get_user_model
    from accounting.models import Agreement, CashAccount, Category, Entity
    from accounting.tests_reports import ReportFixtures
    f = ReportFixtures()
    f.owner = get_user_model().objects.get(username='s18-owner')
    f.member = get_user_model().objects.get(username='s18-accountant')
    f.office = f.owner.accountant_profile.office
    f.customer = Entity.objects.get(office=f.office, name='ΔΟΚΙΜΑΣΤΙΚΟΣ ΠΕΛΑΤΗΣ')
    f.supplier = Entity.objects.get(office=f.office, name='ΔΟΚΙΜΑΣΤΙΚΟΣ ΠΡΟΜΗΘΕΥΤΗΣ')
    f.account = CashAccount.objects.get(office=f.office, name='ΔΟΚΙΜΑΣΤΙΚΟ ΤΑΜΕΙΟ Α')
    f.other = CashAccount.objects.get(office=f.office, name='ΔΟΚΙΜΑΣΤΙΚΟ ΤΑΜΕΙΟ Β')
    f.foreign_account = CashAccount.objects.exclude(office=f.office).get()
    f.foreign = f.foreign_account.office
    f.category = Category.objects.get(office=f.office)
    f.agreement = Agreement.objects.get(office=f.office, description='ΔΟΚΙΜΑΣΤΙΚΗ ΣΥΜΦΩΝΙΑ')
    f.password = os.environ['S31_OWNER_PASSWORD']
    f.request = lambda user=None: client_for(user or f.owner).get('/office/settings/' if user is None else '/').wsgi_request
    return f


def retained_snapshot(previous=None):
    """Hash all original columns/rows; permit only new migration metadata IDs."""
    from django.db import connection
    q = connection.ops.quote_name
    with connection.cursor() as cursor:
        cursor.execute("SET TIME ZONE 'UTC'")
        cursor.execute('SET extra_float_digits=3')
        if previous is None:
            cursor.execute("SELECT table_name,column_name,data_type FROM information_schema.columns WHERE table_schema='public' ORDER BY table_name,ordinal_position")
            tables = {}
            for table, name, kind in cursor.fetchall():
                tables.setdefault(table, {'columns': [], 'maximum': None})['columns'].append([name, kind])
            for table, row in tables.items():
                if table in {'django_migrations', 'django_content_type', 'auth_permission'}:
                    cursor.execute('SELECT coalesce(max(id),0) FROM ' + q(table))
                    row['maximum'] = cursor.fetchone()[0]
        else:
            tables = {table: {'columns': row['columns'], 'maximum': row['maximum']} for table, row in previous.items()}
        result = {}
        for table, row in tables.items():
            values = ['trim_scale(t.' + q(name) + ')' if kind == 'numeric' else 't.' + q(name) for name, kind in row['columns']]
            expression = 'jsonb_build_array(' + ','.join(values) + ')::text'
            where = ' WHERE t.id <= %s' if row['maximum'] is not None else ''
            cursor.execute('SELECT count(*),md5(coalesce(string_agg(md5(' + expression + "),'' ORDER BY md5(" + expression + ")),'')) FROM " + q(table) + ' t' + where,
                           [row['maximum']] if row['maximum'] is not None else [])
            count, checksum = cursor.fetchone()
            result[table] = {**row, 'rows': count, 'checksum': checksum}
    if previous is not None:
        require(result == previous, 'retained_columns_people_passwords_mfa_sessions_or_finance_changed')
    return result


def seed_base():
    from accounting.tests_finance_posting import Fixtures
    from accounting.models import Entity
    from django.db import connection
    f = Fixtures(); f.seed()
    f.owner.set_password(os.environ['S31_OWNER_PASSWORD']); f.owner.save(update_fields=['password'])
    client_for(f.owner)  # Real OTP verification, synthetic device, retained in backup.
    Entity.objects.create(office=f.foreign, name='ΞΕΝΟ ΔΕΔΟΜΕΝΟ ΕΛΕΓΧΟΥ S31', entity_type='CUSTOMER')
    with connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM django_migrations WHERE app='accounting'")
        require(cursor.fetchone()[0] == 20, 'baseline_schema_20_required')
    return {'source_migrations': 20, 'retained': retained_snapshot(), 'synthetic_only': True}


def migrate_forward():
    from django.core.management import call_command
    from django.db import connection
    original = retained_snapshot()
    call_command('migrate', interactive=False, verbosity=0)
    retained_snapshot(original)
    with connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM django_migrations WHERE app='accounting'")
        require(cursor.fetchone()[0] == 26, 'current_schema_26_required')
        cursor.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")
        new_tables = sorted({row[0] for row in cursor.fetchall()} - set(original))
        require(new_tables, 'forward_migrations_added_no_tables')
        for table in new_tables:
            cursor.execute('SELECT count(*) FROM ' + connection.ops.quote_name(table))
            require(cursor.fetchone()[0] == 0, 'migration_created_unreviewed_business_work')
    return {'source_migrations': 20, 'target_migrations': 26, 'old_tables_checked': len(original),
            'original_columns_rows_passwords_mfa_sessions_preserved': True, 'new_business_tables_empty': True,
            'mode': 'clone-only; original database retained; no backward migration'}


def complete_cycle():
    from decimal import Decimal
    from django.core.exceptions import PermissionDenied, ValidationError
    from django.urls import reverse
    from accounting.correction_services import correct_cash, refund_credit, reverse_refund
    from accounting.finance_services import post_transfer
    from accounting.settlement_services import allocate_cash
    from accounting.models import Entity, Transaction
    from accounting.tests_finance_posting import DAY
    from accounting.report_forms import PeriodReportForm
    from accounting.export_selectors import build_document
    f = fixture()
    charge = f.obligation(); source = f.cash()
    original = (source.amount, source.transaction_type, source.transaction_date, source.description)
    allocate_cash(f.member, **f.allocation_values(source, charge))
    require(f.current_balances(charge, source) == (Decimal('75.00'), Decimal('95.00')), 'partial_settlement_75_credit_95_required')
    owner_request = f.request()
    common = {'password': f.password, 'effective_date': DAY, 'reason': 'Συνθετικός πλήρης οικονομικός κύκλος S31'}
    def key():
        import uuid
        return str(uuid.uuid4())
    args = dict(source_cash=source.pk, cash_account=f.account.pk, amount='20.00', **common)
    before = f.snapshot()
    for request, values, error in ((f.request(f.member), args, PermissionDenied),
                                   (owner_request, args | {'password': f.password + ':invalid'}, ValidationError)):
        try:
            refund_credit(request, idempotency_key=key(), **values)
        except error:
            pass
        else:
            raise RuntimeError('owner_MFA_password_or_role_denial_failed')
        require(f.snapshot() == before, 'denied_privileged_action_wrote_finance')
    recent = owner_request.session['s13_mfa_at']; owner_request.session['s13_mfa_at'] = 0
    try:
        refund_credit(owner_request, idempotency_key=key(), **args)
    except ValidationError:
        pass
    else:
        raise RuntimeError('expired_recent_MFA_not_denied')
    finally:
        owner_request.session['s13_mfa_at'] = recent
    require(f.snapshot() == before, 'expired_MFA_action_wrote_finance')
    refund = refund_credit(owner_request, idempotency_key=key(), **args).refund_record
    require(f.current_balances(charge, source) == (Decimal('75.00'), Decimal('75.00')), 'refund_credit_75_required')
    reverse_refund(owner_request, entry_id=refund.entry_id, idempotency_key=key(), **common)
    require(f.current_balances(charge, source) == (Decimal('75.00'), Decimal('95.00')), 'refund_reversal_credit_95_required')
    correct_cash(owner_request, entry_id=source.pk, idempotency_key=key(), **common)
    require(f.current_balances(charge, source) == (Decimal('100.00'), Decimal('0.00')), 'correction_must_release_allocation_and_reopen_debt')
    replacement = f.cash(amount='50.00')
    allocate_cash(f.member, **f.allocation_values(replacement, charge, amount='50.00'))
    post_transfer(f.member, from_account=f.account, to_account=f.other, amount='5.00', transfer_date=DAY,
                  description='Συνθετική εσωτερική μεταφορά S31', idempotency_key=key())
    source.refresh_from_db()
    require((source.amount, source.transaction_type, source.transaction_date, source.description) == original, 'posted_original_changed')
    report = f.report()
    require(report['report_ready'] and (report['total_income'], report['total_expense'], report['net_for_period']) ==
            (Decimal('50.00'), Decimal('0.00'), Decimal('50.00')), 'net_operating_50_required')
    require((report['receivable_remaining'], report['customer_credit']) == (Decimal('50.00'), Decimal('0.00')), 'debt_50_credit_zero_required')
    closing = {row['account'].pk: row['closing'] for row in report['cash_bridge']['rows']}
    require(closing == {f.account.pk: Decimal('145.00'), f.other.pk: Decimal('5.00')}
            and all(row['difference'] == 0 for row in report['cash_bridge']['rows']), 'cash_145_plus_5_required')
    client = client_for(f.member)
    query = {'start_date': DAY.isoformat(), 'end_date': DAY.isoformat(), 'as_of': DAY.isoformat()}
    for name, params in (('summary-report', query), ('client-statement', {'as_of': DAY.isoformat()})):
        response = client.get(reverse(name, args=[f.customer.pk] if name == 'client-statement' else []), params)
        require(response.status_code == 200 and '50,00' in response.content.decode() and 'lang="el"' in response.content.decode(), 'Greek_screen_cycle_totals_failed')
    document = build_document(f.member, PeriodReportForm(query, user=f.member), 'period', 'csv')
    totals = next(s for s in document.sections if s.title == 'Σύνολα λειτουργικών κινήσεων')
    require([row[1] for row in totals.rows] == [Decimal('50.00'), Decimal('0.00'), Decimal('50.00')], 'typed_export_totals_failed')
    for filetype in ('pdf', 'csv'):
        response = client.get(reverse('report-export', args=[filetype]), query)
        require(response.status_code == 200 and 'no-store' in response.get('Cache-Control', ''), 'private_export_failed')
        if filetype == 'pdf':
            from pypdf import PdfReader
            text = '\n'.join(page.extract_text() or '' for page in PdfReader(io.BytesIO(response.content)).pages)
            require('50,00' in text and 'Οικονομική αναφορά' in text, 'actual_PDF_Greek_and_totals_failed')
        else:
            import csv
            rows = list(csv.reader(io.StringIO(response.content.decode('utf-8-sig')), delimiter=';'))
            require(any('50,00' in cell for row in rows for cell in row), 'actual_CSV_totals_failed')
    foreign = Entity.objects.get(office=f.foreign)
    before = f.snapshot()
    for path, params in ((reverse('entity-detail', args=[foreign.pk]), {}),
                         (reverse('client-statement-export', args=[foreign.pk, 'csv']), query),
                         (reverse('summary-report'), query | {'cash_account': str(f.foreign_account.pk)})):
        response = client.get(path, params)
        require(response.status_code in (403, 404) and foreign.name not in response.content.decode('utf-8', errors='replace'), 'foreign_data_not_denied')
    require(f.snapshot() == before, 'denied_read_wrote_finance')
    return {'passed': True, 'charge': '100.00', 'first_receipt': '120.00', 'partial_allocation': '25.00',
            'refund_and_refund_reversal': '20.00', 'corrected_receipt_net': '0.00', 'replacement': '50.00',
            'final_allocation': '50.00', 'final_debt': '50.00', 'final_credit': '0.00',
            'closing_accounts': ['145.00', '5.00'], 'operating_income': '50.00', 'operating_expense': '0.00',
            'original_immutable': True, 'denied_privileged_actions_no_writes': True, 'foreign_reads_exports_filters_denied': True,
            'Greek_screen_and_actual_PDF_CSV_totals_matched': True,
            'scope': 'real domain services and authenticated views with synthetic fixture login and real owner OTP; manual UI acceptance Pending'}


def seed_load():
    from datetime import timedelta
    from django.utils import timezone
    from accounting.models import Entity, Agreement
    from accounting.charge_services import save_terms, post_charge
    from accounting.finance_services import post_cash
    import uuid
    workload = profile(json.loads(Path('/opt/s31/workload.json').read_text()))
    settings = workload['synthetic_envelope']; f = fixture()
    last = timezone.localdate(); first = last - timedelta(days=settings['window_days'] - 1)
    clients = []
    for i in range(settings['clients']):
        entity = Entity.objects.create(office=f.office, name=f'ΣΥΝΘΕΤΙΚΟΣ ΠΕΛΑΤΗΣ ΦΟΡΤΟΥ S31 {i:04}', entity_type='CUSTOMER')
        agreement = Agreement.objects.create(office=f.office, entity=entity, agreement_type='RECEIVABLE',
                    description=f'Συνθετική συμφωνία φόρτου {i:04}', total_amount='100.00', start_date=last)
        terms = agreement.terms_versions.first()
        save_terms(f.member, agreement, billing_mode='ONE_OFF', lifecycle='ACTIVE', expected_revision=terms.revision,
                   reason='Συνθετικό ετήσιο δείγμα φόρτου S31')
        post_charge(f.member, agreement_id=agreement.pk, terms_revision=agreement.terms_versions.first().revision,
                    amount='100.00', effective_date=last, due_date=last, reason='Συνθετικό δείγμα S31', idempotency_key=str(uuid.uuid4()))
        clients.append(entity)
    for i in range(settings['ordinary_movements']):
        # All synthetic dates are real, within the rolling year and account opening.
        day = max(f.account.opening_date, first + timedelta(days=i % settings['window_days']))
        post_cash(f.member, amount='1.00', transaction_date=day, transaction_type='INCOME', cash_account=f.account,
                  entity=clients[i % len(clients)], description=f'Συνθετική κίνηση φόρτου S31 {i:04}', idempotency_key=str(uuid.uuid4()))
    return {'synthetic_clients_added': len(clients), 'synthetic_charges_added': len(clients),
            'synthetic_ordinary_movements_added': settings['ordinary_movements'], 'first': first.isoformat(), 'last': last.isoformat(),
            'methods': 'unchanged real charge and cash services; no financial bulk insert or SQL guard bypass'}


def benchmark():
    from concurrent.futures import ThreadPoolExecutor
    from datetime import timedelta
    import http.client
    import threading
    from urllib.parse import urlencode
    from django.conf import settings
    from django.db import close_old_connections
    from django.urls import reverse
    from django.utils import timezone
    f = fixture(); workload = profile(json.loads(Path('/opt/s31/workload.json').read_text()))
    envelope = workload['synthetic_envelope']; end = timezone.localdate(); start = end - timedelta(days=envelope['window_days'] - 1)
    paths = {'list': reverse('transaction-list'), 'detail': reverse('entity-detail', args=[f.customer.pk]),
             'annual_report': reverse('summary-report') + '?' + urlencode({'start_date': start.isoformat(), 'end_date': end.isoformat(), 'as_of': end.isoformat()})}
    # Fifty different DB sessions, one synthetic accountant; no MFA/login rate
    # benchmark is claimed. No cookie or body is written to a log/report.
    cookies = [client_for(f.member).cookies[settings.SESSION_COOKIE_NAME].value for _ in range(envelope['sessions'])]
    require(len(set(cookies)) == envelope['sessions'], '50_distinct_authenticated_sessions_required')
    close_old_connections()
    barrier = threading.Barrier(envelope['sessions'], timeout=60)
    def fetch(cookie, path):
        start_time = time.perf_counter(); status = 0; error = ''
        connection = http.client.HTTPConnection('127.0.0.1', 8000, timeout=envelope['request_timeout_seconds'])
        try:
            connection.request('GET', path, headers={'Host': 's31.example.invalid', 'X-Forwarded-Proto': 'https',
                'Accept-Language': 'en', 'Cookie': settings.SESSION_COOKIE_NAME + '=' + cookie})
            response = connection.getresponse(); status = response.status
            body = response.read(4 * 1024 * 1024 + 1)
            if status != 200 or len(body) > 4 * 1024 * 1024 or b'lang="el"' not in body:
                error = 'unexpected_http_status_body_or_language'
        except (OSError, TimeoutError, http.client.HTTPException):
            error = 'transport_or_timeout'
        finally:
            connection.close()
        return time.perf_counter() - start_time, status, error
    # Warm each route once, excluded and reported separately.
    for path in paths.values():
        _, _, error = fetch(cookies[0], path)
        require(not error, 'HTTP_warmup_failed')
    def session(index):
        local = []
        barrier.wait()
        for cycle in range(envelope['cycles_per_session']):
            # Rotate the start operation; all classes overlap under concurrency.
            keys = list(paths); offset = index % 3
            for key in keys[offset:] + keys[:offset]:
                elapsed, status, error = fetch(cookies[index], paths[key])
                local.append((key, elapsed, status, error))
        return local
    began = time.perf_counter()
    with ThreadPoolExecutor(max_workers=envelope['sessions']) as pool:
        observations = [row for rows in pool.map(session, range(envelope['sessions'])) for row in rows]
    samples = {key: [] for key in paths}; errors = []
    for key, elapsed, status, error in observations:
        samples[key].append(elapsed)
        if error:
            errors.append({'operation': key, 'status': status, 'code': error})
    measured = performance_result(samples, errors, workload)
    return {**measured, 'duration_seconds': time.perf_counter() - began, 'sessions': len(cookies), 'warmup_requests_excluded': 3,
            'samples_seconds': samples, 'error_details': errors,
            'requests': len(observations), 'window_days': envelope['window_days'],
            'report_kind': 'rolling 365-day full-office financial period report; not a 31-day monthly export',
            'authentication_scope': '50 separate fixture-issued authenticated sessions, one synthetic ordinary accountant; real auth/MFA regression in full suite'}


def recovered():
    from decimal import Decimal
    from cryptography.fernet import InvalidToken
    from django.conf import settings
    from django.test import override_settings
    from django.utils import timezone
    from accounting.auth_models import AuthenticatorDevice
    from core.auth_crypto import cipher
    f = fixture()
    device = AuthenticatorDevice.objects.get(user=f.owner, confirmed=True)
    key = device.bin_key
    require(len(key) == 20, 'MFA_seed_not_recovered')
    require(f.owner.check_password(os.environ['S31_OWNER_PASSWORD']), 'owner_password_not_recovered')
    with override_settings(SECRET_KEY=settings.SECRET_KEY + ':wrong-recovery-proof', SECRET_KEY_FALLBACKS=[]):
        try:
            cipher(f.owner.pk, device.secret_salt).decrypt(device.encrypted_secret.encode())
        except InvalidToken:
            pass
        else:
            raise RuntimeError('wrong_signing_key_decrypted_MFA')
    report = f.report(end_date=timezone.localdate().isoformat(), as_of=timezone.localdate().isoformat())
    require(report['report_ready'] and report['total_income'] == Decimal('2050.00')
            and report['receivable_remaining'] == Decimal('20050.00') and report['customer_credit'] == Decimal('2000.00')
            and report['cash_bridge']['known_closing_total'] == Decimal('2150.00')
            and all(row['difference'] == 0 for row in report['cash_bridge']['rows']),
            'restored_financial_totals_do_not_match_cycle_plus_load')
    # A new regular fixture session is tested over real Gunicorn HTTP after
    # fingerprints, not a view mock. This changes only restored auth/session rows.
    result = http_smoke(f)
    owner_response = client_for(f.owner).get('/office/settings/')
    require(owner_response.status_code == 200, 'restored_owner_password_MFA_session_failed')
    return {'required_synthetic_key_material_recovered': True, 'wrong_signing_key_denied': True,
            'restored_http_200': result, 'restored_financial_totals_matched': True,
            'restored_owner_password_and_real_MFA_view_passed': True,
            'real_document_recovery': 'Pending S38; rehearsal media is empty', 'accepted_real_dataset_rpo_rto': 'Pending'}


def http_smoke(f=None):
    import http.client
    from django.conf import settings
    f = f or fixture()
    cookie = client_for(f.member).cookies[settings.SESSION_COOKIE_NAME].value
    connection = http.client.HTTPConnection('127.0.0.1', 8000, timeout=45)
    try:
        connection.request('GET', '/report/', headers={'Host': 's31.example.invalid', 'X-Forwarded-Proto': 'https',
                           'Cookie': settings.SESSION_COOKIE_NAME + '=' + cookie})
        response = connection.getresponse(); body = response.read(4 * 1024 * 1024 + 1)
        require(response.status == 200 and b'lang="el"' in body, 'restored_real_HTTP_failed')
    finally:
        connection.close()
    return True


def main():
    stage = sys.argv[1] if len(sys.argv) == 2 else ''
    actions = {'seed-base': seed_base, 'migrate-forward': migrate_forward, 'cycle': complete_cycle,
               'seed-load': seed_load, 'benchmark': benchmark, 'recovered': recovered, 'http-smoke': http_smoke}
    try:
        require(stage in actions, 'unknown_probe_stage')
        guard(empty=stage == 'seed-base')
        result = actions[stage]()
        print('S31-RESULT ' + json.dumps(result, ensure_ascii=False))
    except Exception as error:
        # No SQL, cookies, password or database payload is emitted on failure.
        diagnostic = {'stage': stage, 'error': type(error).__name__}
        if isinstance(error, RuntimeError) and re.fullmatch(r'[A-Za-z0-9_]{1,150}', str(error)):
            diagnostic['reason'] = str(error)
        print('S31-PROBE-DIAG ' + json.dumps(diagnostic), file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
