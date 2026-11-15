"""S25 marked-database adapter, run by legacy_migration.py in the verified image.

No Django management command or production bypass is installed. Human source
identities/passwords stay archived; synthetic migration actors use real MFA.
"""
from datetime import date
from decimal import Decimal
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, '/app')
from legacy_plan import GROUPS, build_plan, digest, read_json, require

MODELS = {'users': ('auth', 'User'), 'cash_accounts': ('accounting', 'CashAccount'),
    'entities': ('accounting', 'Entity'), 'categories': ('accounting', 'Category'),
    'agreements': ('accounting', 'Agreement'), 'transactions': ('accounting', 'Transaction')}


class DeliberateRollback(RuntimeError):
    pass


class ReplayMismatch(ValueError):
    pass


def guard(kind, *, empty=False):
    from django.db import connection
    nonce = os.environ['S25_NONCE']
    require(connection.vendor == 'postgresql' and connection.settings_dict['NAME'] == 's25_' + kind + '_' + nonce,
        'Η βάση δεν ανήκει στην απομονωμένη δοκιμή S25.')
    with connection.cursor() as c:
        c.execute("SELECT current_user, current_database(), current_setting('server_version_num')::int")
        _, _, version = c.fetchone()
        require(version // 10000 == (15 if kind == 'source' else 17), 'Μη αναμενόμενη έκδοση PostgreSQL.')
        c.execute("SELECT to_regclass('s25_control.identity')")
        exists = c.fetchone()[0]
        if empty:
            require(not exists, 'Η δοκιμαστική βάση έχει ήδη αρχικοποιηθεί.')
            c.execute("SELECT count(*) FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema')")
            require(c.fetchone()[0] == 0, 'Η βάση πρέπει να είναι καινούργια.')
        else:
            require(exists, 'Λείπει η ταυτότητα απομονωμένης βάσης.')
            c.execute('SELECT nonce, kind FROM s25_control.identity')
            require(c.fetchall() == [(nonce, 'source' if kind == 'raw' else kind)], 'Η ταυτότητα βάσης δεν συμφωνεί.')


def marker(kind):
    from django.db import connection
    with connection.cursor() as c:
        c.execute('CREATE SCHEMA s25_control')
        c.execute('CREATE TABLE s25_control.identity(nonce text PRIMARY KEY, kind text NOT NULL)')
        c.execute('INSERT INTO s25_control.identity VALUES (%s,%s)', [os.environ['S25_NONCE'], kind])


def source_models():
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor
    executor = MigrationExecutor(connection)
    return executor, executor.loader.project_state([('accounting', '0002_transaction_agreement_alter_agreement_status_and_more'),
        *executor.loader.graph.leaf_nodes('auth')]).apps


def seed(source):
    from django.db import transaction
    from django.contrib.auth.hashers import make_password
    guard('source', empty=True)
    executor, _ = source_models()
    executor.migrate([('accounting', '0002_transaction_agreement_alter_agreement_status_and_more'),
        *executor.loader.graph.leaf_nodes('auth')])
    _, apps = source_models()
    with transaction.atomic():
        marker('source')
        for group in GROUPS:
            model = apps.get_model(*MODELS[group])
            for row in source[group]:
                values = {k: v for k, v in row.items() if k not in {'created_at', 'updated_at'}}
                if group == 'users':
                    values['password'] = make_password(None)
                model.objects.create(**values)
                # Historical timestamps are source evidence, not fabricated target audit times.
                times = {k: v for k, v in row.items() if k in {'created_at','updated_at'}}
                if times:
                    model.objects.filter(pk=row['id']).update(**times)
    return {'seeded': True, 'source_rows': sum(len(source[g]) for g in GROUPS)}


def export_source(template, kind):
    from django.db import connection, transaction
    guard(kind)
    _, apps = source_models()
    with transaction.atomic(), connection.cursor() as c:
        c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        result = {'schema': 1, 'lineage': template['lineage']}
        for group in GROUPS:
            model = apps.get_model(*MODELS[group]); output = []
            # Only the explicit JSON projection is exported. The logical snapshot
            # separately preserves every original column, including auth metadata.
            fields = sorted({field for row in template[group] for field in row})
            for row in model.objects.order_by('id').values(*fields):
                output.append({key: f'{value:.2f}' if isinstance(value, Decimal) else
                    value.isoformat() if hasattr(value, 'isoformat') else str(value) if key == 'transfer_id' else value
                    for key, value in row.items()})
            result[group] = output
        return result


def initialise(review):
    from django.core.management import call_command
    from django.db import connection, transaction
    from django.contrib.auth import get_user_model
    from accounting.membership import create_office, create_accountant_profile
    from accounting.office_services import audit
    guard('target', empty=True)
    call_command('migrate', interactive=False, verbosity=0)
    from django.db.migrations.recorder import MigrationRecorder
    applied = list(MigrationRecorder(connection).migration_qs.filter(app='accounting').values_list('name',flat=True))
    require(len(applied) == 20 and any(name.startswith('0020_') for name in applied), 'Ο στόχος χρειάζεται ακριβώς το ελεγμένο σχήμα S24/0020.')
    with transaction.atomic():
        marker('target')
        with connection.cursor() as c:
            c.execute('''CREATE SCHEMA s25_import;
                CREATE TABLE s25_import.batch(lineage text PRIMARY KEY, plan_sha256 text NOT NULL,
                    result jsonb NOT NULL, recorded_at timestamptz NOT NULL DEFAULT now());
                CREATE TABLE s25_import.record(lineage text NOT NULL REFERENCES s25_import.batch(lineage)
                    DEFERRABLE INITIALLY DEFERRED, source_key text NOT NULL,
                    source_sha256 text NOT NULL, office_id text, disposition text NOT NULL,
                    target jsonb NOT NULL, source_row jsonb NOT NULL, decision jsonb NOT NULL, review_reference text NOT NULL,
                    recorded_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(lineage,source_key));
                CREATE FUNCTION s25_import.retain() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN RAISE EXCEPTION 'S25 source mapping is append only'; END $$;
                CREATE TRIGGER retain_record BEFORE UPDATE OR DELETE ON s25_import.record
                FOR EACH ROW EXECUTE FUNCTION s25_import.retain();
                CREATE TRIGGER retain_batch BEFORE UPDATE OR DELETE ON s25_import.batch
                FOR EACH ROW EXECUTE FUNCTION s25_import.retain();
                CREATE TRIGGER retain_record_truncate BEFORE TRUNCATE ON s25_import.record
                FOR EACH STATEMENT EXECUTE FUNCTION s25_import.retain();
                CREATE TRIGGER retain_batch_truncate BEFORE TRUNCATE ON s25_import.batch
                FOR EACH STATEMENT EXECUTE FUNCTION s25_import.retain();''')
        for key, choice in review['offices'].items():
            office = create_office(name=choice['name'])
            user = get_user_model().objects.create_user(username='s25_' + key,
                email=key + '@example.invalid', password=os.environ['S25_OWNER_PASSWORD'])
            create_accountant_profile(user_id=user.pk, office_id=office.pk, role='owner')
            audit(office, None, 'office.bootstrap', target=user, operator_ref='S25 synthetic rehearsal')
    return {'initialised': True, 'human_accounts_imported': False}


def actor_request(user):
    from django.test import Client
    from django.urls import reverse
    from django_otp.oath import TOTP
    from accounting.auth_models import AuthenticatorDevice
    client = Client(enforce_csrf_checks=True)
    def post(path, data):
        response = client.get(path)
        require(response.status_code == 200, 'Η δοκιμαστική φόρμα δεν είναι διαθέσιμη.')
        return client.post(path, {**data, 'csrfmiddlewaretoken': client.cookies['csrftoken'].value},
            HTTP_ORIGIN='http://testserver')
    response = post('/login/', {'username': user.username, 'password': os.environ['S25_OWNER_PASSWORD']})
    require(response.status_code == 302, 'Αποτυχία εισόδου δοκιμαστικού υπευθύνου.')
    require(not AuthenticatorDevice.objects.filter(user=user, confirmed=True).exists(), 'Η νέα απομονωμένη βάση αναμένεται χωρίς ενεργή συσκευή.')
    response = post(reverse('mfa-setup'), {'action': 'start', 'password': os.environ['S25_OWNER_PASSWORD']})
    require(response.status_code == 302, 'Αποτυχία έναρξης δοκιμαστικής MFA.')
    device = AuthenticatorDevice.objects.get(user=user, confirmed=False)
    totp = TOTP(device.bin_key, step=30, digits=6); totp.time = time.time()
    response = post(reverse('mfa-setup'), {'otp_token': f'{totp.token():06d}'})
    require(response.status_code == 200 and AuthenticatorDevice.objects.get(pk=device.pk).confirmed, 'Αποτυχία δοκιμαστικής MFA.')
    response = client.get('/')
    require(response.status_code == 200 and response.wsgi_request.user.is_verified(), 'Λείπει η επαληθευμένη συνεδρία.')
    return response.wsgi_request


def replay(plan):
    from django.db import connection
    with connection.cursor() as c:
        c.execute('SELECT plan_sha256,result FROM s25_import.batch WHERE lineage=%s', [plan['lineage']])
        row = c.fetchone()
        if row:
            if row[0] != plan['plan_sha256']:
                raise ReplayMismatch('Η παγωμένη πηγή ή η ανασκόπηση άλλαξε. Δεν έγινε ενημέρωση οικονομικών εγγραφών.')
            return row[1]
    return None


def apply_plan(source, review, *, inject=False):
    from django.db import connection, transaction
    from django.contrib.auth import get_user_model
    from accounting.models import Entity, CashAccount, Category, Agreement, AccountantProfile, AgreementTermsVersion
    from accounting.account_services import save_reference, preview_opening, approve_opening
    from accounting.counterparty_services import FIELDS, save_counterparty
    from accounting.charge_services import save_terms, post_charge
    from accounting.finance_services import post_cash, post_transfer
    from accounting.settlement_services import allocate_cash
    guard('target'); plan = build_plan(source, review)
    require(not plan['unresolved'], 'Υπάρχουν εξαιρέσεις χωρίς καταγεγραμμένη απόφαση.')
    with transaction.atomic(), connection.cursor() as c:
        c.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,25))', [plan['lineage']])
        previous = replay(plan)
        if previous:
            return {**previous, 'replayed': True}
        require(not Entity.objects.exists() and not CashAccount.objects.exists() and not Agreement.objects.exists(), 'Η αρχική βάση δοκιμής πρέπει να μην έχει οικονομικές εγγραφές.')
        actors, requests, offices = {}, {}, {}
        for key in review['offices']:
            user = get_user_model().objects.get(username='s25_' + key)
            requests[key] = actor_request(user); actors[key] = requests[key].user
            offices[key] = AccountantProfile.objects.get(user=user).office_id
        source_rows = {g + ':' + str(row['id']): row for g in GROUPS for row in source[g]}
        states = {entry['key']: entry for entry in plan['entries']}
        mapping = {}
        def actor(key):
            return actors[states[key]['office']]
        def target(group, pk):
            return int(mapping[group + ':' + str(pk)]['id']) if pk is not None else None
        def idem(key):
            return 's25:' + plan['lineage'] + ':' + key
        for key, entry in states.items():
            mapping[key] = {'kind': 'archive', 'id': None}
            if entry['action'] != 'import':
                continue
            row, choice = source_rows[key], review['records'][key]
            if key.startswith('entities:'):
                values = {f: row.get(f) or '' for f in FIELDS if f not in {'is_customer','is_supplier','legal_kind'}}
                values.update({f: choice[f] for f in ('is_customer','is_supplier','legal_kind')})
                result = save_counterparty(actor(key), values)
                mapping[key] = {'kind': 'entity', 'id': str(result.pk)}
            elif key.startswith('cash_accounts:'):
                account = save_reference(CashAccount(name=row['name']), actor(key))
                opening = choice['opening']; amount = Decimal(opening['amount']); at = date.fromisoformat(opening['date'])
                _, token = preview_opening(actor(key), account_id=account.pk, amount=amount, effective_date=at)
                approve_opening(requests[entry['office']], account_id=account.pk, review_token=token, amount=amount,
                    effective_date=at, reason='Μετάπτωση ελεγμένου αρχικού υπολοίπου', review_reference=opening['reference'],
                    password=os.environ['S25_OWNER_PASSWORD'], idempotency_key=idem(key + ':opening'), acknowledged=True)
                mapping[key] = {'kind': 'cashaccount', 'id': str(account.pk)}
        pending = {k for k, e in states.items() if k.startswith('categories:') and e['action'] == 'import'}
        while pending:
            progress = False
            for key in sorted(pending):
                row = source_rows[key]; parent = row.get('parent_id')
                if parent and 'categories:' + str(parent) in pending:
                    continue
                category = save_reference(Category(name=row['name'], parent_id=target('categories', parent)), actor(key))
                mapping[key] = {'kind': 'category', 'id': str(category.pk)}; pending.remove(key); progress = True
            require(progress, 'Κυκλική ή μη διαθέσιμη κατηγορία.')
        for key, entry in states.items():
            if not key.startswith('agreements:') or entry['action'] != 'import':
                continue
            row, choice = source_rows[key], review['records'][key]
            agreement = save_terms(actor(key), Agreement(entity_id=target('entities',row['entity_id']),
                agreement_type=row['agreement_type'], description=row['description'], total_amount=Decimal(row['total_amount']),
                start_date=date.fromisoformat(row['start_date']), status='ACTIVE'), billing_mode=choice['billing_mode'], lifecycle='ACTIVE',
                reason='Μετάπτωση ελεγμένων όρων · ' + choice['reference'])
            terms = AgreementTermsVersion.objects.filter(agreement=agreement).first()
            ids = []
            for pos, charge in enumerate(choice['charges']):
                result = post_charge(actor(key), agreement_id=agreement.pk, terms_revision=terms.revision,
                    amount=Decimal(charge['amount']), effective_date=date.fromisoformat(charge['date']), due_date=date.fromisoformat(charge['due']),
                    period=date.fromisoformat(charge['period']) if charge.get('period') else None,
                    reason='Μετάπτωση ρητής χρέωσης · ' + choice['reference'], idempotency_key=idem(key + ':charge:' + str(pos)))
                ids.append(str(result.pk))
            mapping[key] = {'kind': 'agreement', 'id': str(agreement.pk), 'charges': ids}
        paired = {key for pair in plan['transfers'] for key in pair}
        for pair in plan['transfers']:
            if any(states[k]['action'] == 'opening-component' for k in pair):
                continue
            if any(states[k]['action'] != 'import' for k in pair):
                continue
            outgoing = next(k for k in pair if source_rows[k]['transaction_type'] == 'EXPENSE')
            incoming = next(k for k in pair if source_rows[k]['transaction_type'] == 'INCOME')
            a, b = source_rows[outgoing], source_rows[incoming]
            result = post_transfer(actor(outgoing), from_account=target('cash_accounts',a['cash_account_id']),
                to_account=target('cash_accounts',b['cash_account_id']), amount=Decimal(a['amount']),
                transfer_date=date.fromisoformat(a['transaction_date']), description='Ελεγμένη παλιά εσωτερική μεταφορά', idempotency_key=idem(outgoing + ':pair'))
            from accounting.models import Transaction
            legs = Transaction.objects.filter(office_id=offices[states[outgoing]['office']], transfer_id=result[0].transfer_id)
            for key in pair:
                row = source_rows[key]
                leg = legs.get(cash_account_id=target('cash_accounts',row['cash_account_id']), transaction_type=row['transaction_type'])
                mapping[key] = {'kind': 'transaction', 'id': str(leg.pk)}
        for key, entry in states.items():
            if not key.startswith('transactions:') or entry['action'] not in {'import','hold-unallocated'} or key in paired:
                continue
            row = source_rows[key]
            result = post_cash(actor(key), cash_account=target('cash_accounts',row['cash_account_id']),
                amount=Decimal(row['amount']), transaction_date=date.fromisoformat(row['transaction_date']), transaction_type=row['transaction_type'],
                description=row['description'], remarks=row.get('remarks',''), category=target('categories',row.get('category_id')),
                entity=target('entities',row.get('entity_id')), agreement=None, idempotency_key=idem(key),
                reason='Μετάπτωση γνήσιας κίνησης · ' + review['records'][key]['reference'])
            mapping[key] = {'kind': 'transaction', 'id': str(result.pk)}
        if inject:
            raise DeliberateRollback('S25 deliberate atomic rollback probe')
        allocation_ids = []
        for pos, line in enumerate(plan['expected']['allocations']):
            key, ckey = line['cash'], line['charge']; agreement_key, number = ckey.split('/')
            result = allocate_cash(actor(key), source_cash=int(mapping[key]['id']),
                lines=[{'charge': mapping[agreement_key]['charges'][int(number)], 'amount': Decimal(line['amount'])}],
                effective_date=date.fromisoformat(line['date']), reason='Μετάπτωση ελεγμένης αντιστοίχισης · ' + line['reference'],
                idempotency_key=idem(key + ':allocate:' + str(pos)))
            allocation_ids.append(str(result.pk))
        for key, entry in states.items():
            if key.startswith('cash_accounts:') and entry['action'] == 'import' and not source_rows[key]['is_active']:
                account = CashAccount.objects.get(pk=int(mapping[key]['id'])); account.is_active = False
                save_reference(account, actor(key), expected_version=account.record_version)
            c.execute('INSERT INTO s25_import.record(lineage,source_key,source_sha256,office_id,disposition,target,source_row,decision,review_reference) VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s)',
                [plan['lineage'], key, entry['source_sha256'], str(offices[entry['office']]) if entry['office'] in offices else None,
                 entry['action'], json.dumps(mapping[key]), json.dumps(source_rows[key]), json.dumps(review['records'][key]), entry['review_reference']])
        result = {'plan_sha256': plan['plan_sha256'], 'mapping': mapping, 'allocations': allocation_ids, 'replayed': False}
        c.execute('INSERT INTO s25_import.batch(lineage,plan_sha256,result) VALUES (%s,%s,%s::jsonb)', [plan['lineage'],plan['plan_sha256'],json.dumps(result)])
        c.execute('SET CONSTRAINTS ALL IMMEDIATE')
        return result


def reconcile(source, review):
    from django.contrib.auth import get_user_model
    from accounting.models import Transaction, FinanceAuditEvent, CashAllocation
    from accounting.cash_selectors import cash_accounts
    from accounting.settlement_selectors import charge_balances, cash_sources
    from django.db import connection
    guard('target'); plan = build_plan(source, review); result = replay(plan)
    require(result is not None, 'Δεν υπάρχει ολοκληρωμένη παρτίδα μετάπτωσης.')
    mapping = result['mapping']; checks = []
    source_rows = {g+':'+str(row['id']):row for g in GROUPS for row in source[g]}
    def check(key, field, expected, actual):
        checks.append({'key': key, 'field': field, 'expected': str(expected), 'actual': str(actual), 'matched': expected == actual})
    accounts, charges, cash = {}, {}, {}
    for office in review['offices']:
        user = get_user_model().objects.get(username='s25_' + office); at = date.fromisoformat(review['as_of'])
        accounts.update({str(r.pk): r for r in cash_accounts(user, as_of=at, include_inactive=True)})
        charges.update({str(r.pk): r for r in charge_balances(user, as_of=at)})
        cash.update({str(r.pk): r for r in cash_sources(user, as_of=at)})
    for key, expected in plan['expected']['accounts'].items():
        row = accounts[mapping[key]['id']]
        for field, actual in [('opening', row.opening_balance), ('balance',row.current_balance), ('income',row.operating_income),
                ('expense',row.operating_expense), ('transfer_in',row.transfer_in), ('transfer_out',row.transfer_out)]:
            check(key, field, Decimal(expected[field]), actual)
        raw = plan['raw_account_reconciliation'][key]
        check(key,'source-exclusions',Decimal('0.00'),Decimal(raw['unexplained_difference']) if raw['unexplained_difference'] is not None else None)
    for key, expected in plan['expected']['charges'].items():
        akey, pos = key.split('/'); row = charges[mapping[akey]['charges'][int(pos)]]
        for field, actual in [('amount',row.amount), ('allocated',row.allocated_total), ('outstanding',row.outstanding)]:
            check(key, field, Decimal(expected[field]), actual)
        original = source_rows[akey]; choice = review['records'][akey]['charges'][int(pos)]
        check(key,'agreement',mapping[akey]['id'],str(row.agreement_id))
        check(key,'party',mapping['entities:'+str(original['entity_id'])]['id'],str(row.entity_id))
        check(key,'direction',original['agreement_type'],row.direction)
        check(key,'effective-date',date.fromisoformat(choice['date']),row.effective_date)
        check(key,'due-date',date.fromisoformat(choice['due']),row.due_date)
    for key, expected in plan['expected']['cash'].items():
        row = Transaction.objects.get(pk=int(mapping[key]['id']))
        check(key, 'amount', Decimal(expected['amount']), row.amount)
        check(key, 'transfer', expected['transfer'], row.posting_kind == 'TRANSFER')
        original = source_rows[key]
        check(key,'direction',original['transaction_type'],row.transaction_type)
        check(key,'effective-date',date.fromisoformat(original['transaction_date']),row.transaction_date)
        check(key,'cash-account',mapping['cash_accounts:'+str(original['cash_account_id'])]['id'],str(row.cash_account_id))
        check(key,'party',mapping['entities:'+str(original['entity_id'])]['id'] if original['entity_id'] else None,str(row.entity_id) if row.entity_id else None)
        audit = FinanceAuditEvent.objects.get(entry=row)
        check(key,'audit-actor',True,audit.actor_id is not None and audit.origin == 'user' and audit.office_id == row.office_id)
        if row.entity_id and not expected['transfer']:
            check(key, 'allocated', Decimal(expected['allocated']), cash[str(row.pk)].allocated_total)
            check(key, 'unallocated', Decimal(expected['unallocated']), cash[str(row.pk)].available_credit)
    for pair in plan['transfers']:
        if pair[0] not in plan['expected']['cash']:
            continue
        legs = [Transaction.objects.get(pk=int(mapping[key]['id'])) for key in pair]
        check(pair[0],'paired-transfer',True,legs[0].transfer_id == legs[1].transfer_id
            and legs[0].cash_account_id != legs[1].cash_account_id
            and {r.transaction_type for r in legs} == {'INCOME','EXPENSE'}
            and Transaction.objects.filter(transfer_id=legs[0].transfer_id,office_id=legs[0].office_id).count() == 2)
    for pos, line in enumerate(plan['expected']['allocations']):
        command = result['allocations'][pos]
        row = CashAllocation.objects.get(command_id=command)
        akey, number = line['charge'].split('/')
        check(line['cash'], 'allocation-source', mapping[line['cash']]['id'], str(row.source_cash_id))
        check(line['cash'], 'allocation-charge', mapping[akey]['charges'][int(number)], str(row.charge_id))
        check(line['cash'], 'allocation-amount', Decimal(line['amount']), row.amount)
        check(line['cash'], 'allocation-date', date.fromisoformat(line['date']), row.effective_date)
    check('ledger', 'source-coverage', len(plan['entries']), len(mapping))
    check('cash', 'row-count', len(plan['expected']['cash']), Transaction.objects.count())
    check('audit', 'actor-required', False, FinanceAuditEvent.objects.filter(actor__isnull=True).exists())
    check('audit', 'events-recorded', True, FinanceAuditEvent.objects.exists())
    with connection.cursor() as c:
        c.execute('SELECT source_key,source_sha256 FROM s25_import.record ORDER BY source_key')
        ledger = dict(c.fetchall())
    for entry in plan['entries']:
        check(entry['key'], 'retained-source-digest', entry['source_sha256'], ledger.get(entry['key']))
    return {'all_matched': all(c['matched'] for c in checks), 'checks': checks,
        'accounts': len(accounts), 'charges': len(charges), 'source_coverage': plan['coverage'],
        'legacy_status_trusted': False, 'live_financial_acceptance': 'Pending'}


def main():
    require(os.environ.get('S25_SYNTHETIC') == '1', 'Η εκτέλεση επιτρέπεται μόνο στην απομονωμένη συνθετική δοκιμή.')
    os.environ['DJANGO_SETTINGS_MODULE'] = 'legacy_settings'
    import django
    django.setup()
    payload = json.load(sys.stdin); source, review = payload['source'], payload['review']
    require(review.get('mode') == 'synthetic' and source.get('lineage') == 'synthetic-s25-v1', 'Η εκτέλεση δέχεται μόνο τη συνθετική πηγή S25.')
    action = sys.argv[1]
    if action == 'seed':
        result = seed(source)
    elif action in {'export-source','export-raw'}:
        result = export_source(source, 'source' if action == 'export-source' else 'raw')
    elif action == 'init':
        result = initialise(review)
    elif action in {'apply','inject-failure'}:
        result = apply_plan(source, review, inject=action == 'inject-failure')
    elif action == 'changed-replay':
        changed = json.loads(json.dumps(review))
        changed['authorisation_reference'] += '-CHANGED'
        try:
            apply_plan(source,changed)
        except ReplayMismatch:
            result = {'changed_payload_denied':True}
        else:
            raise ValueError('Η αλλαγμένη παρτίδα έπρεπε να απορριφθεί.')
    elif action == 'reconcile':
        result = reconcile(source, review)
    else:
        raise ValueError('Άγνωστη λειτουργία δοκιμής.')
    print('S25-RESULT ' + json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    try:
        main()
    except DeliberateRollback:
        print('S25-INJECTED-ROLLBACK', file=sys.stderr)
        sys.exit(42)
    except Exception as error:
        # Raw DB/provider output can contain source values; reports stay private.
        import traceback
        frames = [f for f in traceback.extract_tb(error.__traceback__) if f.filename.startswith(('/app/','/opt/s25/'))]
        frame = frames[-1] if frames else None
        print('S25-WORKER ' + json.dumps({'error':type(error).__name__, 'action':sys.argv[1],
            'function':frame.name if frame else None, 'line':frame.lineno if frame else None,
            'trace':[{'file':Path(f.filename).name,'function':f.name,'line':f.lineno} for f in frames[-4:]],
            'sqlstate':getattr(error.__cause__,'sqlstate',None),
            'reason':'Operation stopped; source retained'}), file=sys.stderr)
        sys.exit(1)
