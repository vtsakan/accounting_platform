"""Use the exact S29 report and unpaged paginator querysets in one snapshot."""
from django.utils import timezone
from core.locale import greek_date
from .export_schema import Document,ExportError,Provenance,section
from .report_selectors import read_snapshot,period_report,annual_report

ROW_LIMITS={'csv':10000,'pdf':2000}
TITLES={'period':'Οικονομική αναφορά περιόδου','statement':'Οικονομική καρτέλα συναλλασσομένου',
        'annual':'Δωδεκάμηνη εικόνα αμοιβών και εξοφλήσεων'}
BALANCES=(('posted_receivable_total','Καθαρές χρεώσεις πελατών'),('receivable_allocated','Αντιστοιχισμένο πελατών'),
    ('receivable_remaining','Ανεξόφλητες χρεώσεις πελατών'),('customer_credit','Αδιάθετη πίστωση πελατών'),
    ('posted_payable_total','Καθαρές χρεώσεις προμηθευτών'),('payable_allocated','Αντιστοιχισμένο προμηθευτών'),
    ('payable_remaining','Ανεξόφλητες υποχρεώσεις προμηθευτών'),('supplier_advance','Προκαταβολές προμηθευτών'))


def full_rows(result,keys,limit):
    pages=[result[key] for key in keys]
    # Counts and rows come from the same S29 querysets before pagination.
    if sum(p.paginator.count for p in pages)>limit:
        raise ExportError('Η αναφορά υπερβαίνει το όριο εξαγωγής. Περιορίστε τον συναλλασσόμενο ή τις ημερομηνίες και δοκιμάστε ξανά.',status=422)
    return {key:list(result[key].paginator.object_list[:limit+1]) for key in keys}


def details(data,as_of):
    sections=[section('Λειτουργικές κινήσεις',('identifier','date','entity','account','description','direction','income','expense'),
        ((str(t.pk),t.transaction_date,t.entity.name if t.entity else 'Χωρίς σύνδεση',t.cash_account.name,t.description,
          t.get_posting_kind_display(),t.report_income,t.report_expense) for t in data['cash_page'])),
        section('Χρεώσεις έως '+greek_date(as_of),('identifier','source','date','due','entity','description','direction','gross','net','allocated','remaining'),
        ((str(c.pk),c.source_key,c.effective_date,c.due_date,c.entity.name,c.description,
          c.get_direction_display()+(' · Αντιλογισμένη' if c.reversed_by_day else ''),c.amount,c.net_amount,c.allocated_total,c.outstanding) for c in data['charge_page'])),
        section('Αρχικές κινήσεις και αδιάθετα ποσά έως '+greek_date(as_of),('identifier','date','entity','direction','gross','allocated','refunded','credit'),
        ((str(t.pk),t.transaction_date,t.entity.name,t.get_transaction_type_display()+(' · Αντιλογισμένη' if t.reversed_by_day else ''),
          t.amount,t.allocated_total,t.refunded_total,t.available_credit) for t in data['credit_page']))]
    if 'event_page' in data:
        sections.append(section('Αντιστοιχίσεις και αποδεσμεύσεις στην περίοδο κινήσεων',('identifier','date','direction','cash','charge','amount'),
            ((str(e['event_id']),e['effective_date'],e['kind'],str(e['source_cash_id']),str(e['charge_id']),e['amount']) for e in data['event_page'])))
    return sections


def build_document(user,form,kind,filetype):
    if kind not in TITLES or filetype not in ROW_LIMITS:raise ValueError('Unknown export selection')
    with read_snapshot(user) as office:
        report=annual_report(user,form) if kind=='annual' else period_report(user,form,statement=kind=='statement')
        if not report.get('report_ready'):raise ExportError('Ελέγξτε τα φίλτρα της αναφοράς πριν από την εξαγωγή.')
        values=form.cleaned_data;as_of=report['report_as_of'];entity=report['report_entity']
        pages=['cash_page','charge_page','credit_page']+(['event_page'] if kind=='statement' else [])
        data=full_rows(report,pages,ROW_LIMITS[filetype])
        identity=[('Αναφορά',TITLES[kind]),('Γραφείο',report['report_office'].name),('Ημερομηνία υπολοίπων',greek_date(as_of)),
            ('Βάση','Καταχωρισμένες κινήσεις, χρεώσεις και αντιστοιχίσεις. Δεν περιλαμβάνονται φορολογικές εκτιμήσεις.'),
            ('Σελίδες','Περιλαμβάνονται όλες οι σελίδες των αναλυτικών πινάκων, με τα ίδια φίλτρα.'),
            ('Άγνωστο ποσό','Άγνωστο σημαίνει ότι δεν υπάρχει επιβεβαιωμένο αρχικό υπόλοιπο στην ημερομηνία αναφοράς.'),
            ('Διαθέσιμα ποσά','Η αδιάθετη πίστωση δεν αφαιρείται αυτόματα από άλλες χρεώσεις.')]
        if kind=='annual':
            identity.extend([('Έτος',str(report['year'])),('Ανάλυση πηγών',str(report['selected_month'])+'/'+str(report['year'])),
                ('Μηνιαία βάση','Χρεώσεις στον μήνα ισχύος, εισπράξεις στον μήνα κίνησης, αντιστοιχίσεις και υπόλοιπα της χρέωσης έως την ημερομηνία αναφοράς.')])
        else:
            identity.extend([('Κινήσεις από',greek_date(report['report_start']) if report['report_start'] else 'Αρχική καταγραφή'),
                ('Κινήσεις έως',greek_date(report['report_end'])),
                ('Βάση υπολοίπων','Τα υπόλοιπα και οι αρχικές κινήσεις πίστωσης αφορούν όλο το ιστορικό του συναλλασσομένου έως την ημερομηνία υπολοίπων. Τα φίλτρα κατηγορίας, ταμείου, περιγραφής και κατεύθυνσης περιορίζουν μόνο τις λειτουργικές κινήσεις.')])
        for key in ('cash_account','category','transaction_type','query'):
            value=values.get(key)
            if value:
                label=form.fields[key].label
                if key=='transaction_type':value=dict(form.fields[key].choices)[value]
                identity.append((str(label),str(value)))
        sections=[section('Ταυτότητα και βάση αναφοράς',('label','value'),identity),
            section('Γραφείο',('identifier','description'),[(str(office),report['report_office'].name)])]
        if entity:
            sections.append(section('Συναλλασσόμενος',('identifier','entity','vat'),[(str(entity.pk),entity.name,entity.vat_number or '')]))
        else:
            sections.append(section('Επιλογή συναλλασσομένου',('label','value'),[('Συναλλασσόμενοι','Όλοι του γραφείου')]))
        if kind=='annual':
            keys=('month','gross','reversed','net','income','allocated','remaining','credit')
            sections.append(section('Δώδεκα μήνες',keys,((r['period'],r['gross'],r['reversed'],r['net'],r['receipts'],r['allocated'],r['remaining'],r['credit']) for r in report['monthly_rows'])))
            t=report['annual_totals'];o=report['outside_year'];s=report['snapshot_totals']
            sections.append(section('Σύνολα έτους',('label','gross','reversed','net','income','allocated','remaining','credit'),
                [('Σύνολο έτους',t['gross'],t['reversed'],t['net'],t['receipts'],t['allocated'],t['remaining'],t['credit'])]))
            sections.append(section('Συμφωνία με συνολική καρτέλα',('label','net','allocated','remaining','credit'),[
                ('Επιλεγμένο έτος',t['net'],t['allocated'],t['remaining'],t['credit']),
                ('Εκτός έτους έως την ημερομηνία υπολοίπων',o['net'],o['allocated'],o['remaining'],o['credit']),
                ('Σύνολο καρτέλας',s['receivable_charged'],s['receivable_allocated'],s['receivable_remaining'],s['customer_credit'])]))
        else:
            sections.append(section('Σύνολα λειτουργικών κινήσεων',('label','amount'),
                [('Λειτουργικές εισπράξεις',report['total_income']),('Λειτουργικές πληρωμές',report['total_expense']),('Καθαρή λειτουργική ροή',report['net_for_period'])]))
            for key,title in [('income_by_category','Εισπράξεις ανά κατηγορία'),('expense_by_category','Πληρωμές ανά κατηγορία')]:
                sections.append(section(title,('description','amount'),((r['category__name'] or 'Χωρίς κατηγορία',r['total_amount']) for r in report[key])))
            sections.append(section('Χρεώσεις και διαθέσιμα ποσά έως '+greek_date(as_of),('label','amount'),((label,report[key]) for key,label in BALANCES)))
            if kind=='period':
                bridge=report['cash_bridge']
                sections.append(section('Βάση ταμειακής συμφωνίας',('label','value'),[
                    ('Πλήρη ταμεία','Όλες οι φυσικές εισροές, εκροές, μεταφορές και διορθώσεις. Τα φίλτρα κατηγορίας, συναλλασσομένου, περιγραφής και κατεύθυνσης δεν επιμερίζουν το αρχικό υπόλοιπο.'),
                    ('Ημερομηνία τελικού υπολοίπου',greek_date(bridge['as_of']))]))
                sections.append(section('Συμφωνία πλήρων επιλεγμένων ταμείων',('account','opening','inflow','outflow','adjustments','closing','difference'),
                    ((r['account'].name,r['opening'],r['inflow'],r['outflow'],r['adjustments'],r['closing'],r['difference']) for r in bridge['rows'])))
                sections.append(section('Υποσύνολο επιβεβαιωμένων ταμείων',('label','amount'),[('Υποσύνολο επιβεβαιωμένων τελικών υπολοίπων',bridge['known_closing_total'])]))
                sections.append(section('Πληρότητα αρχικών υπολοίπων',('label','value'),[('Ταμεία χωρίς διαθέσιμο αρχικό υπόλοιπο',str(bridge['unknown_count']))]))
            if report['legacy_unreviewed_count']:
                sections.append(section('Παλιές κινήσεις προς έλεγχο',('label','value'),[('Πλήθος',str(report['legacy_unreviewed_count'])),
                    ('Πίστωση','Τα διαθέσιμα προς αντιστοίχιση ποσά αφορούν μόνο τις ελεγμένες αρχικές κινήσεις.')]))
        sections.extend(details(data,as_of))
        if sum(len(part.rows) for part in sections)>ROW_LIMITS[filetype]+100:
            raise ExportError('Η αναφορά περιέχει πάρα πολλές γραμμές για εξαγωγή. Περιορίστε τα φίλτρα.',status=422)
        return Document(TITLES[kind],str(office),report['report_office'].name,as_of,timezone.now(),tuple(sections),Provenance(source_dates=(as_of,)))
