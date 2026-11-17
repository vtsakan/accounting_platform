"""Read-only snapshots: each aggregate and paged detail shares its queryset."""
from contextlib import contextmanager
from datetime import date,timedelta
from decimal import Decimal
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import connection,transaction
from django.db.models import CharField,DecimalField,F,Q,Sum,Value
from django.db.models.functions import Coalesce,TruncMonth
from django.utils import timezone
from .capabilities import require_capability
from .cash_selectors import cash_accounts
from .models import Agreement,AllocationRelease,CashAdjustment,CashAllocation,Entity,Transaction
from .movement_selectors import filtered_movements,operating_movements,operating_component,operating_totals,movement_totals,business_direction_condition
from .office_access import records
from .settlement_selectors import charge_balances,cash_sources,settlement_totals

ZERO=Decimal('0.00')


@contextmanager
def read_snapshot(user):
    # Existing outer transactions (including historical TestCase fixtures) retain
    # their isolation. Normal HTTP requests start a repeatable read-only snapshot.
    nested=connection.in_atomic_block
    with transaction.atomic():
        if not nested:
            with connection.cursor() as cursor:cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        yield require_capability(user,'finance.read').office_id


def page(rows,number,size):
    result=Paginator(rows,size).get_page(number or 1)
    result.object_list=list(result.object_list)  # Materialise money before snapshot exit.
    return result


def total(rows,field):
    return rows.aggregate(value=Coalesce(Sum(field),Value(ZERO),output_field=DecimalField()))['value']


def balance_values(values):
    return {**values,'posted_receivable_total':values['receivable_charged'],'posted_payable_total':values['payable_charged']}


def checked(user,form,office):
    if form.office_id!=office:raise PermissionDenied('Η πρόσβαση στο γραφείο άλλαξε. Συνδεθείτε ξανά.')
    return form.is_valid()


def cash_bridge(user,office,values):
    """Full selected-account balances; no attribution of opening cash to clients."""
    end=values.get('end_date') or values['as_of'];start=values.get('start_date')
    closing=cash_accounts(user,as_of=end,include_inactive=True)
    if values.get('cash_account'):closing=closing.filter(pk=values['cash_account'].pk)
    accounts=list(closing);opening={}
    if start and start>date.min:
        opening={a.pk:a for a in cash_accounts(user,as_of=start-timedelta(days=1),include_inactive=True)}
    result=[]
    for account in accounts:
        known=account.current_balance is not None
        beginning=opening.get(account.pk).current_balance if start and account.pk in opening else None
        if known:
            beginning=beginning if beginning is not None else account.opening_balance
            first=max(account.opening_date,start) if start else account.opening_date
            rows=Transaction.objects.filter(office_id=office,cash_account=account,transaction_date__gte=first,transaction_date__lte=end)
            flows=movement_totals(rows)
            adjustment=total(CashAdjustment.objects.filter(office_id=office,account=account,effective_date__gte=first,effective_date__lte=end),'amount')
            expected=beginning+flows['net_for_period']+adjustment
            difference=account.current_balance-expected
        else:
            beginning=adjustment=expected=difference=None;flows={'total_income':None,'total_expense':None}
        result.append({'account':account,'opening':beginning,'inflow':flows['total_income'],'outflow':flows['total_expense'],
            'adjustments':adjustment,'closing':account.current_balance,'difference':difference,'known':known})
    return {'rows':result,'as_of':end,'unknown_count':sum(not r['known'] for r in result),
        'known_closing_total':sum((r['closing'] for r in result if r['known']),ZERO)}


def legacy_aliases(user,entity=None):
    # Preserve historical S12 financial probes; product reports render only the
    # separately named posted-charge/allocated/outstanding projections.
    from .finance_services import legacy_settlement
    rows=records(Agreement,user).filter(status='ACTIVE')
    if entity:rows=rows.filter(entity=entity)
    return {key:rows.filter(agreement_type=direction).annotate(paid=legacy_settlement('transactions__')).aggregate(
        value=Coalesce(Sum(F('total_amount')-F('paid'),output_field=DecimalField()),Value(ZERO),output_field=DecimalField()))['value']
        for direction,key in [('RECEIVABLE','accounts_receivable'),('PAYABLE','accounts_payable')]}


def allocation_events(office,values,entity):
    fields=('effective_date','recorded_at','event_id','charge_id','source_cash_id','amount','kind')
    allocations=CashAllocation.objects.filter(office_id=office,command__state='completed',effective_date__lte=values['end_date'] or values['as_of'])
    releases=AllocationRelease.objects.filter(office_id=office,command__state='completed',effective_date__lte=values['end_date'] or values['as_of'])
    if entity:
        allocations=allocations.filter(charge__entity=entity);releases=releases.filter(allocation__charge__entity=entity)
    if values.get('start_date'):
        allocations=allocations.filter(effective_date__gte=values['start_date']);releases=releases.filter(effective_date__gte=values['start_date'])
    a=allocations.order_by().annotate(event_id=F('pk'),kind=Value('Αντιστοίχιση',output_field=CharField())).values(*fields)
    b=releases.order_by().annotate(event_id=F('pk'),charge_id=F('allocation__charge_id'),source_cash_id=F('allocation__source_cash_id'),
        amount=-F('allocation__amount'),kind=Value('Αποδέσμευση',output_field=CharField())).values(*fields)
    return a.union(b,all=True).order_by('effective_date','recorded_at','event_id')


def period_report(user,form,*,statement=False):
    with read_snapshot(user) as office:
        if not checked(user,form,office):return {'report_ready':False,'total_income':ZERO,'total_expense':ZERO,'net_for_period':ZERO}
        values=form.cleaned_data;as_of=values['as_of'];entity=values.get('entity');size=values['page_size']
        cash=operating_movements(filtered_movements(user,form,business_direction=True)).filter(transaction_date__lte=as_of)
        cash=cash.annotate(report_income=operating_component('INCOME'),report_expense=operating_component('EXPENSE'))
        charges=charge_balances(user,entity=entity,as_of=as_of).select_related('entity')
        sources=cash_sources(user,entity=entity,as_of=as_of)
        balances=balance_values(settlement_totals(user,entity=entity,as_of=as_of))
        income=list(cash.values('category__name').annotate(total_amount=Sum(operating_component('INCOME'))).exclude(total_amount=0).order_by('-total_amount'))
        expense=list(cash.values('category__name').annotate(total_amount=Sum(operating_component('EXPENSE'))).exclude(total_amount=0).order_by('-total_amount'))
        result={'report_ready':True,'report_office':require_capability(user,'finance.read').office,'report_entity':entity,
            'report_start':values.get('start_date'),'report_end':values.get('end_date') or as_of,'report_as_of':as_of,
            **operating_totals(cash),**balances,**legacy_aliases(user,entity),
            'income_by_category':income,'expense_by_category':expense,
            'cash_page':page(cash,values.get('page'),size),'charge_page':page(charges,values.get('charge_page'),size),
            'credit_page':page(sources,values.get('credit_page'),size),
            'legacy_unreviewed_count':Transaction.objects.filter(office_id=office,posting_kind='LEGACY',transaction_date__lte=as_of,
                **({'entity':entity} if entity else {})).count()}
        result['cash_bridge']=cash_bridge(user,office,values) if not statement else None
        if statement:
            result['event_page']=page(allocation_events(office,values,entity),values.get('event_page'),size)
        return result


def annual_report(user,form):
    with read_snapshot(user) as office:
        if not checked(user,form,office):return {'report_ready':False}
        values=form.cleaned_data;year=values['year'];as_of=values['as_of'];entity=values.get('entity');size=values['page_size']
        charges=charge_balances(user,entity=entity,as_of=as_of).filter(direction='RECEIVABLE',effective_date__year=year).select_related('entity')
        cash=Transaction.objects.filter(office_id=office,transaction_date__year=year,transaction_date__lte=as_of).select_related('cash_account','entity')
        if entity:cash=cash.filter(entity=entity)
        cash=operating_movements(cash).filter(business_direction_condition('INCOME')).annotate(report_income=operating_component('INCOME'),report_expense=operating_component('EXPENSE'))
        credit=cash_sources(user,entity=entity,as_of=as_of).filter(transaction_type='INCOME',transaction_date__year=year)
        charge_groups={r['month'].month:r for r in charges.order_by().annotate(month=TruncMonth('effective_date')).values('month').annotate(
            gross=Sum('amount'),net=Sum('net_amount'),allocated=Sum('allocated_total'),remaining=Sum('outstanding'))}
        cash_groups={r['month'].month:r['value'] for r in cash.order_by().annotate(month=TruncMonth('transaction_date')).values('month').annotate(value=Sum('report_income'))}
        credit_groups={r['month'].month:r['value'] for r in credit.order_by().annotate(month=TruncMonth('transaction_date')).values('month').annotate(value=Sum('available_credit'))}
        rows=[]
        for month in range(1,13):
            values_for_month=charge_groups.get(month,{})
            row={'month':month,'period':date(year,month,1),'receipts':cash_groups.get(month,ZERO),'credit':credit_groups.get(month,ZERO)}
            row.update({name:values_for_month.get(name,ZERO) for name in ('gross','net','allocated','remaining')})
            row['reversed']=row['gross']-row['net'];rows.append(row)
        totals={name:sum((row[name] for row in rows),ZERO) for name in ('gross','reversed','net','allocated','remaining','receipts','credit')}
        snapshot=settlement_totals(user,entity=entity,as_of=as_of)
        outside={'net':snapshot['receivable_charged']-totals['net'],'allocated':snapshot['receivable_allocated']-totals['allocated'],
            'remaining':snapshot['receivable_remaining']-totals['remaining'],'credit':snapshot['customer_credit']-totals['credit']}
        selected=values['month']
        return {'report_ready':True,'report_office':require_capability(user,'finance.read').office,'report_entity':entity,
            'report_as_of':as_of,'year':year,'monthly_rows':rows,'annual_totals':totals,'outside_year':outside,'snapshot_totals':snapshot,
            'selected_month':selected,'cash_page':page(cash.filter(transaction_date__month=selected).order_by('-transaction_date','-pk'),values.get('page'),size),
            'charge_page':page(charges.filter(effective_date__month=selected),values.get('charge_page'),size),
            'credit_page':page(credit.filter(transaction_date__month=selected),values.get('credit_page'),size)}


def dashboard_report(user):
    from .workspace_selectors import workspace_snapshot
    with read_snapshot(user):
        day=timezone.localdate();snapshot=workspace_snapshot(user,as_of=day)
        snapshot['snapshot_totals']=settlement_totals(user,as_of=day)
        snapshot['unpaid_clients']=list(charge_balances(user,as_of=day).filter(direction='RECEIVABLE',outstanding__gt=0)
            .order_by().values('entity_id','entity__name').annotate(remaining=Sum('outstanding')).order_by('-remaining','entity_id')[:10])
        # workspace_snapshot already materialises account balances. Its recent
        # queryset is materialised here to retain the same reporting snapshot.
        snapshot['recent_transactions']=list(snapshot['recent_transactions'])
        return snapshot
