"""One scoped, paged history over retained records; never a second money ledger."""
import calendar
from datetime import date

from django.core.paginator import Paginator
from django.db import connection
from django.urls import reverse
from django.utils import timezone

from .models import CounterpartyNote, Entity
from .office_access import record

# Every arm joins the same trusted office/entity scope. All user filters,
# offsets and limits are parameters; only fixed predicates are composed.
EVENTS_SQL = """
WITH scope AS (SELECT %s::uuid AS office_id, %s::bigint AS entity_id), journal AS (
 SELECT 'terms:'||v.id::text AS event_id, 'agreement'::text AS kind,
  v.effective_date AS event_day, v.recorded_at, v.direction,
  CASE WHEN v.revision=1 THEN 'Συμφωνία' ELSE 'Αλλαγή όρων συμφωνίας' END::text AS label,
  v.description::text AS title, v.agreed_amount::numeric AS amount,
  coalesce(u.username,'Δεν καταγράφηκε')::text AS actor_label,
  v.agreement_id, NULL::bigint AS cash_id, ('Έκδοση '||v.revision::text)::text AS detail,
  ''::text AS body
 FROM accounting_agreementtermsversion v
 JOIN scope s ON v.office_id=s.office_id AND v.entity_id=s.entity_id
 LEFT JOIN auth_user u ON u.id=v.actor_id
 UNION ALL
 SELECT 'agreement:'||a.id::text, 'agreement', a.start_date, a.created_at, a.agreement_type,
  'Συμφωνία χωρίς καταγεγραμμένη έκδοση όρων', a.description, a.total_amount,
  'Δεν καταγράφηκε', a.id, NULL::bigint, 'Αρχική εγγραφή', ''
 FROM accounting_agreement a JOIN scope s ON a.office_id=s.office_id AND a.entity_id=s.entity_id
 WHERE NOT EXISTS (SELECT 1 FROM accounting_agreementtermsversion v WHERE v.agreement_id=a.id AND v.office_id=a.office_id)
 UNION ALL
 SELECT 'charge:'||c.id::text, 'charge', c.effective_date, c.recorded_at, c.direction,
  'Χρέωση', c.description, c.amount, coalesce(u.username,'Δεν καταγράφηκε'),
  c.agreement_id, NULL::bigint, 'Προθεσμία '||to_char(c.due_date,'DD/MM/YYYY'), ''
 FROM accounting_charge c JOIN scope s ON c.office_id=s.office_id AND c.entity_id=s.entity_id
 LEFT JOIN auth_user u ON u.id=c.actor_id
 UNION ALL
 SELECT 'cash:'||t.id::text, 'cash', t.transaction_date, t.created_at,
  CASE t.transaction_type WHEN 'INCOME' THEN 'RECEIVABLE' WHEN 'EXPENSE' THEN 'PAYABLE' ELSE '' END,
  CASE WHEN t.posting_kind='REVERSAL' THEN 'Αντιλογισμός κίνησης'
       WHEN t.posting_kind='REFUND' THEN 'Επιστροφή χρημάτων'
       WHEN t.posting_kind='TRANSFER' THEN 'Εσωτερική μεταφορά'
       WHEN t.transaction_type='INCOME' THEN 'Είσπραξη' ELSE 'Πληρωμή' END,
  t.description, t.amount, coalesce(u.username,'Δεν καταγράφηκε'),
  t.agreement_id, t.id, ca.name, t.remarks
 FROM accounting_transaction t JOIN scope s ON t.office_id=s.office_id AND t.entity_id=s.entity_id
 JOIN accounting_cashaccount ca ON ca.id=t.cash_account_id AND ca.office_id=t.office_id
 LEFT JOIN accounting_financecommand cmd ON cmd.id=t.command_id AND cmd.office_id=t.office_id
 LEFT JOIN auth_user u ON u.id=cmd.actor_id
 UNION ALL
 SELECT 'allocation:'||a.id::text, 'allocation', a.effective_date, a.recorded_at, c.direction,
  'Αντιστοίχιση πληρωμής', c.description, a.amount, coalesce(u.username,'Δεν καταγράφηκε'),
  c.agreement_id, a.source_cash_id, 'Σύνδεση με χρέωση', ''
 FROM accounting_cashallocation a JOIN accounting_charge c ON c.id=a.charge_id AND c.office_id=a.office_id
 JOIN scope s ON a.office_id=s.office_id AND c.entity_id=s.entity_id
 JOIN accounting_settlementcommand cmd ON cmd.id=a.command_id AND cmd.office_id=a.office_id AND cmd.state='completed'
 LEFT JOIN auth_user u ON u.id=cmd.actor_id
 UNION ALL
 SELECT 'release:'||r.id::text, 'release', r.effective_date, r.recorded_at, c.direction,
  'Αποδέσμευση αντιστοίχισης', c.description, a.amount, coalesce(u.username,'Δεν καταγράφηκε'),
  c.agreement_id, a.source_cash_id, 'Η αρχική αντιστοίχιση διατηρείται', ''
 FROM accounting_allocationrelease r JOIN accounting_cashallocation a ON a.id=r.allocation_id AND a.office_id=r.office_id
 JOIN accounting_charge c ON c.id=a.charge_id AND c.office_id=r.office_id
 JOIN scope s ON r.office_id=s.office_id AND c.entity_id=s.entity_id
 JOIN accounting_settlementcommand cmd ON cmd.id=r.command_id AND cmd.office_id=r.office_id AND cmd.state='completed'
 LEFT JOIN auth_user u ON u.id=cmd.actor_id
 UNION ALL
 SELECT 'charge-reversal:'||r.id::text, 'correction', r.effective_date, r.recorded_at, c.direction,
  'Αντιλογισμός χρέωσης', c.description, c.amount, coalesce(u.username,'Δεν καταγράφηκε'),
  c.agreement_id, NULL::bigint, cmd.reason, ''
 FROM accounting_chargereversal r JOIN accounting_charge c ON c.id=r.charge_id AND c.office_id=r.office_id
 JOIN scope s ON r.office_id=s.office_id AND c.entity_id=s.entity_id
 JOIN accounting_financecorrection cmd ON cmd.id=r.correction_id AND cmd.office_id=r.office_id AND cmd.state='completed'
 LEFT JOIN auth_user u ON u.id=cmd.actor_id
 UNION ALL
 SELECT 'note:'||n.id::text, 'note', (n.created_at AT TIME ZONE 'Europe/Athens')::date,
  n.created_at, 'NOTE', 'Σημείωση', '', NULL::numeric, n.actor_label,
  NULL::bigint, NULL::bigint, '', n.body
 FROM accounting_counterpartynote n JOIN scope s ON n.office_id=s.office_id AND n.entity_id=s.entity_id
)
"""

MONTHS = ('Ιανουάριος', 'Φεβρουάριος', 'Μάρτιος', 'Απρίλιος', 'Μάιος', 'Ιούνιος',
    'Ιούλιος', 'Αύγουστος', 'Σεπτέμβριος', 'Οκτώβριος', 'Νοέμβριος', 'Δεκέμβριος')


def month_bounds(month):
    year, number = map(int, month.split('-'))
    first = date(year, number, 1)
    last = date(year, number, calendar.monthrange(year, number)[1])
    return first, last


def decorate_event(row, entity_id):
    row['tone'] = 'blue' if row['kind'] == 'note' or not row['direction'] else (
        'green' if row['direction'] == 'RECEIVABLE' else 'red')
    row['direction_label'] = {'RECEIVABLE': 'Εισπρακτέα / έσοδο', 'PAYABLE': 'Πληρωτέα / έξοδο'}.get(row['direction'], '')
    row['anchor'] = row['event_id'].replace(':', '-')
    if row['agreement_id']:
        row['url'] = reverse('agreement-detail', args=[row['agreement_id']])
    elif row['cash_id']:
        row['url'] = reverse('cash-allocation-add', args=[row['cash_id']])
    else:
        row['url'] = ''
    return row


class JournalRows:
    """Paginator adapter: SQL COUNT and LIMIT/OFFSET, never materialise all events."""
    def __init__(self, entity, values=None, *, empty=False):
        self.entity = entity
        self.values = values or {}
        self.empty = empty

    def where(self, *, month=None):
        predicates = ['TRUE']
        params = [str(self.entity.office_id), self.entity.pk]
        if self.empty:
            predicates.append('FALSE')
        for field, operator in (('start_date', '>='), ('end_date', '<=')):
            if self.values.get(field):
                predicates.append('event_day ' + operator + ' %s')
                params.append(self.values[field])
        for field in ('kind', 'direction'):
            if self.values.get(field):
                predicates.append(field + '=%s')
                params.append(self.values[field])
        if self.values.get('q'):
            literal = self.values['q'].replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
            predicates.append('(title ILIKE %s OR body ILIKE %s OR detail ILIKE %s OR actor_label ILIKE %s)')
            params.extend(['%' + literal + '%'] * 4)
        if month or self.values.get('view') == 'month':
            first, last = month_bounds(month or self.values['month'])
            predicates += ['event_day >= %s', 'event_day <= %s']
            params += [first, last]
        return ' AND '.join(predicates), params

    def count(self):
        where, params = self.where()
        with connection.cursor() as cursor:
            cursor.execute(EVENTS_SQL + ' SELECT count(*) FROM journal WHERE ' + where, params)
            return cursor.fetchone()[0]

    def __getitem__(self, key):
        if not isinstance(key, slice) or key.step is not None:
            raise TypeError('Journal rows require a bounded page slice')
        start, stop = key.start or 0, key.stop
        if start < 0 or stop is None or stop < start or stop - start > 100:
            raise ValueError('Journal pages must contain at most 100 events')
        where, params = self.where()
        with connection.cursor() as cursor:
            cursor.execute(EVENTS_SQL + ' SELECT * FROM journal WHERE ' + where +
                ' ORDER BY event_day DESC, recorded_at DESC, event_id DESC LIMIT %s OFFSET %s',
                params + [stop - start, start])
            names = [column[0] for column in cursor.description]
            return [decorate_event(dict(zip(names, row)), self.entity.pk) for row in cursor.fetchall()]

    def calendar(self, month):
        where, params = self.where(month=month)
        with connection.cursor() as cursor:
            cursor.execute(EVENTS_SQL + """ SELECT event_day,
                count(*) FILTER (WHERE kind<>'note' AND direction='RECEIVABLE') AS green,
                count(*) FILTER (WHERE kind<>'note' AND direction='PAYABLE') AS red,
                count(*) FILTER (WHERE kind='note' OR direction='') AS blue
                FROM journal WHERE """ + where + ' GROUP BY event_day ORDER BY event_day', params)
            counts = {row[0]: dict(zip(('green', 'red', 'blue'), row[1:])) for row in cursor.fetchall()}
        first, last = month_bounds(month)
        weeks = []
        for days in calendar.Calendar(firstweekday=0).monthdayscalendar(first.year, first.month):
            weeks.append([{'day': date(first.year, first.month, day), 'number': day,
                'counts': counts.get(date(first.year, first.month, day), {}),
                'today': date(first.year, first.month, day) == timezone.localdate()} if day else None for day in days])
        previous = (first.year - 1, 12) if first.month == 1 else (first.year, first.month - 1)
        following = (first.year + 1, 1) if first.month == 12 else (first.year, first.month + 1)
        return {'weeks': weeks, 'label': f'{MONTHS[first.month - 1]} {first.year}',
            'previous': '%04d-%02d' % previous if previous[0] >= 1900 else '',
            'next': '%04d-%02d' % following if following[0] <= 2200 else ''}


def journal_page(user, entity_id, form, number=None):
    entity = record(Entity, user, entity_id)
    valid = form.is_valid()
    rows = JournalRows(entity, form.cleaned_data if valid else None, empty=not valid)
    page = Paginator(rows, 25).get_page(number)
    page.object_list = list(page.object_list)
    month = form.cleaned_data.get('month') if valid else timezone.localdate().strftime('%Y-%m')
    return {'entity': entity, 'journal_page': page, 'journal_calendar': rows.calendar(month)}


def card_summary(user, entity, agreements, movements):
    from .movement_selectors import movement_totals
    # The entity has already been read within the same snapshot and office.
    counts = {'agreements': agreements.count(),
        'receivable_agreements': agreements.filter(agreement_type='RECEIVABLE').count(),
        'payable_agreements': agreements.filter(agreement_type='PAYABLE').count(),
        'notes': CounterpartyNote.objects.filter(office_id=entity.office_id, entity=entity).count()}
    counts.update(movement_totals(movements.filter(transaction_date__lte=timezone.localdate())))
    return {'card_stats': counts, 'journal_preview': JournalRows(entity)[:8]}
