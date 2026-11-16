"""S25 exact-decimal, read-only planning. No Django, DB or cloud imports."""
from collections import Counter
from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re
import uuid

GROUPS = ('users', 'cash_accounts', 'entities', 'categories', 'agreements', 'transactions')
MONEY = re.compile(r'-?(?:0|[1-9][0-9]{0,9})\.[0-9]{2}\Z')
KEY = re.compile(r'[a-z][a-z0-9_-]{0,39}\Z')
ZERO = Decimal('0.00')


def require(value, message):
    if not value:
        raise ValueError(message)


def digest(value):
    return 'sha256:' + hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'Διπλό πεδίο JSON: ' + key)
        result[key] = value
    return result


def read_json(path):
    path = Path(path)
    require(path.stat().st_size <= 64 * 1024 * 1024, 'Το αρχείο υπερβαίνει τα 64 MiB.')
    return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique_object,
        parse_float=lambda _: (_ for _ in ()).throw(ValueError('Τα ποσά γράφονται ως κείμενο με δύο δεκαδικά.')),
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Μη πεπερασμένος αριθμός JSON.')))


def cents(value, *, signed=False):
    require(isinstance(value, str) and MONEY.fullmatch(value), 'Μη έγκυρο ακριβές ποσό EUR.')
    try:
        result = Decimal(value)
    except InvalidOperation:
        raise ValueError('Μη έγκυρο ποσό EUR.') from None
    require(abs(result) <= Decimal('9999999999.99') and (signed or result > 0), 'Μη επιτρεπόμενο ποσό EUR.')
    return result


def day(value):
    require(isinstance(value, str) and re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', value), 'Μη έγκυρη ημερομηνία.')
    return date.fromisoformat(value)


def positive_id(value):
    require(type(value) is int and 0 < value <= 9223372036854775807, 'Μη έγκυρη ταυτότητα πηγής.')
    return value


def record_key(group, key):
    return group + ':' + str(positive_id(key))


def afm(value):
    require(isinstance(value, str), 'Μη έγκυρος Α.Φ.Μ.')
    # Match the approved S15 syntax policy; this is not an AFM checksum/registry check.
    value = value.translate(str.maketrans('０１２３４５６７８９', '0123456789'))
    value = re.sub(r'[\s\-]', '', value).upper()
    if value.startswith('EL'):
        value = value[2:]
    require(not value or re.fullmatch(r'[0-9]{9}', value), 'Μη έγκυρος Α.Φ.Μ.')
    return value


def build_plan(source, review):
    """Every source identity gets one disposition; genuine cash can be held unallocated."""
    require(source.get('schema') == 1 and review.get('schema') == 1, 'Άγνωστη έκδοση μετάπτωσης.')
    require(KEY.fullmatch(source.get('lineage', '')) and review.get('lineage') == source['lineage'], 'Η πηγή δεν συμφωνεί με τη χαρτογράφηση.')
    require(review.get('source_sha256') == digest(source), 'Η πηγή άλλαξε μετά την ανασκόπηση.')
    require(review.get('mode') in {'synthetic', 'authorised-copy'} and review.get('authorisation_reference'), 'Απαιτείται αναφορά εξουσιοδοτημένου αντιγράφου.')
    as_of = day(review['as_of'])
    offices = review['offices']
    require(isinstance(offices, dict) and offices and all(KEY.fullmatch(k) for k in offices), 'Ελέγξτε τα γραφεία της χαρτογράφησης.')
    rows, index = {}, {}
    for group in GROUPS:
        require(isinstance(source.get(group), list), 'Λείπει ο πίνακας ' + group)
        rows[group] = source[group]
        for row in rows[group]:
            key = record_key(group, row['id'])
            require(key not in index, 'Διπλή ταυτότητα πηγής: ' + key)
            index[key] = row
    decisions = review.get('records', {})
    require(not (set(decisions) - set(index)), 'Η χαρτογράφηση περιέχει ανύπαρκτες εγγραφές.')
    issues = {key: [] for key in index}
    def issue(key, code):
        if code not in issues[key]:
            issues[key].append(code)
    def owner(key):
        return decisions.get(key, {}).get('office')
    def link(key, field, group, *, required=False):
        value = index[key].get(field)
        if value is None and not required:
            return None
        try:
            target = record_key(group, value)
        except (ValueError, TypeError):
            issue(key, 'invalid-reference'); return None
        if target not in index or owner(key) != owner(target):
            issue(key, 'foreign-or-missing-reference'); return None
        return target
    for key, row in index.items():
        choice = decisions.get(key, {})
        if owner(key) not in offices:
            issue(key, 'unmapped-office')
        if not choice.get('reference'):
            issue(key, 'missing-review-reference')
        if not key.startswith('users:'):
            user_id = choice.get('responsible_user')
            try:
                user_key = record_key('users', user_id)
                if user_key not in index or owner(user_key) != owner(key) or decisions.get(user_key, {}).get('action') != 'archive':
                    issue(key, 'unmapped-user')
            except (ValueError, TypeError):
                issue(key, 'unmapped-user')
        try:
            for field in ('created_at', 'updated_at'):
                if field in row:
                    require(isinstance(row[field], str) and len(row[field]) <= 40, 'Μη έγκυρη χρονοσήμανση.')
            if key.startswith(('cash_accounts:', 'entities:', 'categories:')):
                require(isinstance(row.get('name'), str) and row['name'].strip(), 'Λείπει η ονομασία.')
            if key.startswith('cash_accounts:'):
                cents(row['opening_balance'], signed=True)
                require(type(row['is_active']) is bool, 'Μη έγκυρη κατάσταση ταμείου.')
                opening = choice['opening']
                require(day(opening['date']) <= as_of and opening['reference'], 'Λείπει η ανασκόπηση αρχικού υπολοίπου.')
                cents(opening['amount'], signed=True)
            elif key.startswith('entities:'):
                afm(row.get('vat_number') or '')
                require(choice.get('legal_kind') in {'INDIVIDUAL', 'BUSINESS'}, 'Επιλέξτε νομική μορφή.')
                require(type(choice.get('is_customer')) is bool and type(choice.get('is_supplier')) is bool
                    and (choice['is_customer'] or choice['is_supplier']), 'Επιλέξτε ρόλους συναλλασσομένου.')
            elif key.startswith('categories:'):
                link(key, 'parent_id', 'categories')
            elif key.startswith('agreements:'):
                party = link(key, 'entity_id', 'entities', required=True)
                require(row['agreement_type'] in {'RECEIVABLE', 'PAYABLE'}, 'Μη έγκυρη κατεύθυνση συμφωνίας.')
                cents(row['total_amount']); require(day(row['start_date']) <= as_of, 'Μελλοντική συμφωνία.')
                require(choice.get('billing_mode') in {'ONE_OFF', 'MONTHLY'} and choice.get('lifecycle') == 'ACTIVE', 'Μη ελεγμένοι όροι συμφωνίας.')
                require(row.get('description') and row['status'] in {'ACTIVE', 'COMPLETED'}, 'Απαιτείται χωριστή αρχειακή αντιμετώπιση ακύρωσης.')
                if party:
                    require(decisions.get(party, {}).get('is_customer' if row['agreement_type'] == 'RECEIVABLE' else 'is_supplier'), 'Ακατάλληλος ρόλος συναλλασσομένου.')
                charges = choice.get('charges', [])
                require(charges and (choice['billing_mode'] != 'ONE_OFF' or len(charges) == 1), 'Ελέγξτε το ρητό πρόγραμμα χρεώσεων.')
                periods = set()
                for charge in charges:
                    amount = cents(charge['amount']); effective = day(charge['date'])
                    require(day(row['start_date']) <= effective <= as_of and day(charge['due']) >= effective, 'Μη έγκυρες ημερομηνίες χρέωσης.')
                    period = charge.get('period')
                    if choice['billing_mode'] == 'MONTHLY':
                        require(day(period).day == 1 and period[:7] == charge['date'][:7], 'Μη έγκυρη μηνιαία περίοδος.')
                        first = day(row['start_date']).replace(day=1)
                        require(day(period) >= first, 'Ο μήνας προηγείται της συμφωνίας.')
                        require(amount == cents(row['total_amount']) or (day(period) == first and day(row['start_date']).day != 1), 'Ο πλήρης μήνας χρειάζεται το ελεγμένο ποσό όρων.')
                    else:
                        require(period is None and amount == cents(row['total_amount']), 'Μη έγκυρη εφάπαξ χρέωση.')
                    require(period not in periods, 'Διπλή περίοδος χρέωσης.'); periods.add(period)
            elif key.startswith('transactions:'):
                cents(row['amount'])
                require(row['transaction_type'] in {'INCOME', 'EXPENSE'}, 'Η παλιά μεταφορά χρειάζεται δύο ρητά αντίθετα σκέλη.')
                require(day(row['transaction_date']) <= as_of, 'Μελλοντική κίνηση.')
                require(isinstance(row.get('description'), str) and row['description'].strip(), 'Λείπει η περιγραφή κίνησης.')
                uuid.UUID(row['transfer_id'])
                link(key, 'cash_account_id', 'cash_accounts', required=True)
                link(key, 'entity_id', 'entities')
                link(key, 'category_id', 'categories')
                # An invalid old agreement link is an allocation exception, not lost cash.
                aid = row.get('agreement_id')
                if aid is not None:
                    agreement_key = record_key('agreements', aid)
                    agreement = index.get(agreement_key)
                    valid = agreement and owner(agreement_key) == owner(key) and agreement['entity_id'] == row.get('entity_id') and agreement['agreement_type'] == ('RECEIVABLE' if row['transaction_type'] == 'INCOME' else 'PAYABLE')
                    if not valid and choice.get('action') != 'hold-unallocated':
                        issue(key, 'invalid-settlement-link')
        except (ValueError, TypeError, KeyError, InvalidOperation):
            issue(key, 'invalid-fields-or-unreviewed-terms')
    # Name/AFM collisions and category cycles never merge identities silently.
    for group, fields in [('cash_accounts', ('name',)), ('categories', ('name', 'parent_id')), ('entities', ('vat_number',))]:
        seen = {}
        for row in rows[group]:
            key = record_key(group, row['id'])
            value = tuple((afm(row.get(f) or '') if f == 'vat_number' and not issues[key] else row.get(f)) for f in fields)
            if group == 'entities' and not value[0]:
                continue
            identity = (owner(key), *value)
            if identity in seen:
                issue(key, 'duplicate-identity'); issue(seen[identity], 'duplicate-identity')
            seen[identity] = key
    for row in rows['categories']:
        key = record_key('categories', row['id']); visited = set(); current = row
        while current and current.get('parent_id') is not None:
            if current['id'] in visited:
                issue(key, 'category-cycle'); break
            visited.add(current['id']); current = index.get('categories:' + str(current['parent_id']))
    transfer_groups = {}
    for row in rows['transactions']:
        transfer_groups.setdefault(row['transfer_id'], []).append(record_key('transactions', row['id']))
    pairs, paired = [], set()
    for group, keys in transfer_groups.items():
        proof = review.get('transfers', {}).get(group)
        if len(keys) == 1 and not proof:
            continue  # The old UUID default alone proves nothing about a transfer.
        valid = len(keys) == 2 and proof and proof.get('reference') and sorted(proof.get('legs', [])) == sorted(index[k]['id'] for k in keys)
        if valid:
            a, b = (index[k] for k in keys)
            valid = (not any(issues[k] for k in keys) and owner(keys[0]) == owner(keys[1])
                and {a['transaction_type'], b['transaction_type']} == {'INCOME', 'EXPENSE'}
                and a['amount'] == b['amount'] and a['transaction_date'] == b['transaction_date']
                and a['cash_account_id'] != b['cash_account_id']
                and not any(r.get(f) for r in (a, b) for f in ('entity_id', 'agreement_id', 'category_id')))
            before = [day(index[k]['transaction_date']) < day(decisions['cash_accounts:' + str(index[k]['cash_account_id'])]['opening']['date']) for k in keys] if valid else []
            valid = valid and len(set(before)) == 1
        if valid:
            pairs.append(sorted(keys)); paired.update(keys)
        else:
            for key in keys:
                issue(key, 'ambiguous-transfer')
    # Referencing a quarantined master is blocked even when its numeric FK exists.
    changed = True
    while changed:
        changed = False
        for key, row in index.items():
            for field, group in [('cash_account_id','cash_accounts'), ('category_id','categories'), ('entity_id','entities'), ('parent_id','categories')]:
                if row.get(field) is not None:
                    ref = group + ':' + str(row[field])
                    if ref in issues and (issues[ref] or decisions.get(ref, {}).get('action') != 'import') and 'blocked-master' not in issues[key]:
                        issue(key, 'blocked-master'); changed = True
    # A later master/ownership denial also holds the *other* transfer leg.
    retained_pairs = []
    for pair in pairs:
        if any(issues[k] or decisions.get(k,{}).get('action') != 'import' for k in pair):
            for key in pair:
                issue(key, 'ambiguous-transfer')
                paired.discard(key)
        else:
            retained_pairs.append(pair)
    pairs = retained_pairs
    entries, unresolved = [], []
    for key, row in index.items():
        choice = decisions.get(key, {}); action = choice.get('action')
        if issues[key]:
            action = 'quarantine'
            if choice.get('action') != 'quarantine' or not choice.get('reason') or not choice.get('reference'):
                unresolved.append(key)
        elif key.startswith('users:'):
            action = 'archive'  # Never create/activate human users from a legacy password table.
        elif action not in {'import', 'hold-unallocated', 'archive', 'quarantine'}:
            action = 'quarantine'; unresolved.append(key)
        elif action in {'archive', 'quarantine'} and not choice.get('reason'):
            unresolved.append(key)
        if key.startswith('transactions:') and action in {'import', 'hold-unallocated'}:
            opening = decisions['cash_accounts:' + str(row['cash_account_id'])]['opening']
            if day(row['transaction_date']) < day(opening['date']):
                action = 'opening-component'
        entries.append({'key': key, 'source_sha256': digest(row), 'office': owner(key), 'action': action,
            'issues': sorted(issues[key]), 'review_reference': choice.get('reference', ''),
            'disposition_reason': choice.get('reason','')})
    states = {e['key']: e['action'] for e in entries}
    expected = {'accounts': {}, 'charges': {}, 'cash': {}, 'allocations': []}
    for row in rows['cash_accounts']:
        key = record_key('cash_accounts', row['id'])
        if states[key] != 'import':
            continue
        opening = cents(row['opening_balance'], signed=True)
        for cash in rows['transactions']:
            if cash['cash_account_id'] == row['id'] and states['transactions:' + str(cash['id'])] == 'opening-component':
                opening += cents(cash['amount']) * (1 if cash['transaction_type'] == 'INCOME' else -1)
        if opening != cents(decisions[key]['opening']['amount'], signed=True):
            unresolved.append(key + ':opening-mismatch')
        expected['accounts'][key] = dict(opening=f'{opening:.2f}', balance=f'{opening:.2f}', income='0.00', expense='0.00', transfer_in='0.00', transfer_out='0.00')
    for row in rows['agreements']:
        key = record_key('agreements', row['id'])
        if states[key] != 'import':
            continue
        for pos, charge in enumerate(decisions[key]['charges']):
            expected['charges'][key + '/' + str(pos)] = {'amount': charge['amount'], 'allocated': '0.00', 'outstanding': charge['amount']}
    for row in rows['transactions']:
        key = record_key('transactions', row['id'])
        if states[key] not in {'import', 'hold-unallocated'}:
            continue
        amount = cents(row['amount']); account = expected['accounts'].get('cash_accounts:' + str(row['cash_account_id']))
        require(account is not None, 'Η αποδεκτή κίνηση δεν έχει αποδεκτό ταμείο.')
        direction = row['transaction_type']
        account['balance'] = f"{Decimal(account['balance']) + amount * (1 if direction == 'INCOME' else -1):.2f}"
        field = ('transfer_in' if direction == 'INCOME' else 'transfer_out') if key in paired else ('income' if direction == 'INCOME' else 'expense')
        account[field] = f'{Decimal(account[field]) + amount:.2f}'
        expected['cash'][key] = {'amount': row['amount'], 'allocated': '0.00', 'unallocated': row['amount'], 'transfer': key in paired}
        allocations = decisions[key].get('allocations', [])
        if states[key] == 'hold-unallocated' and allocations:
            unresolved.append(key + ':held-cash-allocation')
        for allocation in allocations:
            require(type(allocation.get('charge')) is int and allocation['charge'] >= 0, 'Μη έγκυρη θέση χρέωσης.')
            aid = positive_id(allocation['agreement']); ckey = 'agreements:' + str(aid) + '/' + str(allocation['charge'])
            agreement = index.get('agreements:' + str(aid)); target = expected['charges'].get(ckey)
            valid = (key not in paired and states[key] == 'import' and agreement and target
                and owner('agreements:' + str(aid)) == owner(key) and agreement['entity_id'] == row.get('entity_id')
                and agreement['agreement_type'] == ('RECEIVABLE' if direction == 'INCOME' else 'PAYABLE'))
            require(valid, 'Μη επιτρεπόμενη ρητή αντιστοίχιση: ' + key)
            amount = cents(allocation['amount']); at = day(allocation['date'])
            charge = decisions['agreements:' + str(aid)]['charges'][allocation['charge']]
            require(max(day(row['transaction_date']), day(charge['date'])) <= at <= as_of and allocation.get('reference'), 'Μη έγκυρη ημερομηνία ή αναφορά αντιστοίχισης.')
            cash_total = Decimal(expected['cash'][key]['allocated']) + amount
            charge_total = Decimal(target['allocated']) + amount
            require(cash_total <= cents(row['amount']) and charge_total <= cents(target['amount']), 'Υπέρβαση ποσού αντιστοίχισης.')
            expected['cash'][key].update(allocated=f'{cash_total:.2f}', unallocated=f'{cents(row["amount"]) - cash_total:.2f}')
            target.update(allocated=f'{charge_total:.2f}', outstanding=f'{cents(target["amount"]) - charge_total:.2f}')
            # Reviewed charge is an integer position; workers need its canonical
            # agreement/position key. Source metadata must not overwrite either ID.
            expected['allocations'].append({**allocation, 'cash': key, 'charge': ckey})
    raw_accounts = {}
    for row in rows['cash_accounts']:
        key = record_key('cash_accounts',row['id'])
        if key not in expected['accounts']:
            continue
        raw = cents(row['opening_balance'],signed=True); excluded = ZERO; unpriced = []
        for cash in rows['transactions']:
            if cash.get('cash_account_id') != row['id']:
                continue
            ckey = record_key('transactions',cash['id'])
            try:
                if day(cash['transaction_date']) > as_of:
                    continue
                require(cash['transaction_type'] in {'INCOME','EXPENSE'}, 'Άγνωστη κατεύθυνση πηγής.')
                signed = cents(cash['amount'],signed=True) * (1 if cash['transaction_type'] == 'INCOME' else -1)
                raw += signed
                if states[ckey] not in {'import','hold-unallocated','opening-component'}:
                    excluded += signed
            except (ValueError,KeyError,TypeError):
                unpriced.append(ckey)
        accepted = Decimal(expected['accounts'][key]['balance'])
        raw_accounts[key] = {'raw_balance':f'{raw:.2f}' if not unpriced else None,
            'accepted_balance':f'{accepted:.2f}','excluded_signed_cash':f'{excluded:.2f}',
            'unexplained_difference':f'{raw-accepted-excluded:.2f}' if not unpriced else None,
            'unpriced_source_rows':unpriced}
    obligations = {}
    for row in rows['agreements']:
        key = record_key('agreements',row['id'])
        lines = [value for name,value in expected['charges'].items() if name.startswith(key+'/')]
        if not lines:
            continue
        charged = sum((Decimal(r['amount']) for r in lines),ZERO)
        settled = sum((Decimal(r['allocated']) for r in lines),ZERO)
        obligations[key] = {'source_total':row['total_amount'],'source_status':row['status'],
            'reviewed_charged':f'{charged:.2f}','allocated':f'{settled:.2f}',
            'outstanding':f'{charged-settled:.2f}','derived_state':'SETTLED' if charged == settled else 'OPEN'}
    plan = {'schema': 1, 'lineage': source['lineage'], 'source_sha256': digest(source), 'review_sha256': digest(review),
        'as_of': review['as_of'], 'entries': entries, 'transfers': pairs, 'expected': expected,
        'coverage': dict(Counter(e['action'] for e in entries)), 'unresolved': sorted(set(unresolved)),
        'raw_account_reconciliation':raw_accounts,'obligation_reconciliation':obligations,
        'mode': review['mode'], 'live_cutover_approved': False,
        'financial_acceptance': 'Pending', 'all_source_identities_covered': len(entries) == len(index)}
    plan['plan_sha256'] = digest(plan)
    return plan
