"""Immutable presentation data: serializers do no database or money arithmetic."""
from dataclasses import dataclass
from datetime import date,datetime
from decimal import Decimal


class ExportError(Exception):
    def __init__(self,message,*,status=400):
        super().__init__(message);self.status=status


@dataclass(frozen=True)
class Column:
    key:str
    label:str
    kind:str='text'
    weight:float=1


@dataclass(frozen=True)
class Section:
    title:str
    columns:tuple[Column,...]
    rows:tuple[tuple,...]

    def __post_init__(self):
        if any(len(row)!=len(self.columns) for row in self.rows):raise ValueError('Export row shape differs from columns')
        if len({c.key for c in self.columns})!=len(self.columns):raise ValueError('Duplicate export column')
        for row in self.rows:
            for column,value in zip(self.columns,row):
                if value is None:continue
                if column.kind=='money' and (not isinstance(value,Decimal) or not value.is_finite() or value!=value.quantize(Decimal('.01'))):
                    raise ValueError('Export money must be exact finite Decimal cents')
                if column.kind in {'date','month'} and type(value) is not date:raise ValueError('Export date must be a date')


@dataclass(frozen=True)
class Provenance:
    kind:str='posted'
    source_dates:tuple[date,...]=()
    rule_version:str=''

    def __post_init__(self):
        if self.kind not in {'posted','estimate'}:raise ValueError('Unknown export provenance')
        if any(type(day) is not date for day in self.source_dates):raise ValueError('Provenance dates required')
        if self.kind=='estimate' and (not self.source_dates or not self.rule_version.strip()):
            raise ValueError('S59 estimates require source dates and rule version')
        if self.kind=='posted' and self.rule_version:raise ValueError('Posted reports have no forecast rule version')

    @property
    def label(self):
        return 'Καταχωρισμένα οικονομικά στοιχεία' if self.kind=='posted' else 'Εκτίμηση — δεν αποτελεί καταχωρισμένη ταμειακή κίνηση'


@dataclass(frozen=True)
class Document:
    title:str
    office_id:str
    office_name:str
    as_of:date
    generated_at:datetime
    sections:tuple[Section,...]
    provenance:Provenance


COLUMNS={key:Column(key,label,kind,weight) for key,label,kind,weight in (
    ('label','Μέγεθος','text',2),('value','Στοιχείο','text',4),
    ('identifier','Αναγνωριστικό','identifier',1.5),('source','Πηγή χρέωσης','identifier',1.6),
    ('cash','Κίνηση','identifier',1.3),('charge','Χρέωση','identifier',1.5),
    ('date','Ημερομηνία','date',1),('due','Προθεσμία','date',1),('month','Μήνας','month',1),
    ('entity','Συναλλασσόμενος','text',2),('vat','ΑΦΜ','identifier',1),
    ('description','Περιγραφή','text',3),('direction','Κατεύθυνση','text',1.3),('account','Ταμείο','text',2),
    ('amount','Ποσό EUR','money',1.1),('gross','Αρχικό ποσό EUR','money',1.1),
    ('reversed','Αντιλογισμοί EUR','money',1.1),('net','Καθαρό ποσό EUR','money',1.1),
    ('income','Λειτουργικές εισπράξεις EUR','money',1.1),('expense','Λειτουργικές πληρωμές EUR','money',1.1),
    ('allocated','Αντιστοιχισμένο EUR','money',1.1),('remaining','Ανεξόφλητο EUR','money',1.1),
    ('refunded','Επιστροφές EUR','money',1.1),('credit','Αδιάθετο ποσό EUR','money',1.1),
    ('opening','Αρχικό υπόλοιπο EUR','money',1.1),('inflow','Εισερχόμενα EUR','money',1.1),
    ('outflow','Εξερχόμενα EUR','money',1.1),('adjustments','Διορθώσεις EUR','money',1.1),
    ('closing','Τελικό υπόλοιπο EUR','money',1.1),('difference','Διαφορά συμφωνίας EUR','money',1.1),
)}


def section(title,keys,rows):
    return Section(title,tuple(COLUMNS[key] for key in keys),tuple(tuple(row) for row in rows))
