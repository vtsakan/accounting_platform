"""Reviewed financial failures become Greek field/form errors, never SQL text."""
from django.core.exceptions import ValidationError

MESSAGES={
    'cr012_budget_limit':'Η ενέργεια υπερβαίνει το συμφωνημένο συνολικό ποσό. Ανανεώστε τη συμφωνία και ελέγξτε τις χρεώσεις και τις μελλοντικές αλλαγές όρων.',
    'cr012_monthly_limit':'Η χρέωση υπερβαίνει το συμφωνημένο ποσό της μηνιαίας περιόδου.',
    'cr012_selection_scope':'Η χρέωση δεν ανήκει στον επιλεγμένο συναλλασσόμενο και στη σωστή κατεύθυνση.',
    'cr012_selection_allocation':'Η αντιστοίχιση δεν ολοκληρώθηκε. Ελέγξτε το διαθέσιμο υπόλοιπο της χρέωσης.',
    'cr012_selection_immutable':'Η αρχική επιλογή χρέωσης διατηρείται. Για αλλαγή απαιτείται η διαδικασία διόρθωσης.',
}


def add_financial_error(form,error):
    if isinstance(error,ValidationError):
        if hasattr(error,'error_dict'):
            for name,values in error.error_dict.items():
                form.add_error(name if name in form.fields else None,values)
        else:form.add_error(None,error.messages)
        return
    cause=getattr(error,'__cause__',None)
    if getattr(cause,'sqlstate',None) not in {'23505','23514','40001','40P01'}:raise error
    name=getattr(getattr(cause,'diag',None),'constraint_name',None)
    form.add_error(None,MESSAGES.get(name,'Η καταχώριση δεν ολοκληρώθηκε. Ανανεώστε τα στοιχεία και επαναλάβετε την ίδια επιβεβαίωση.'))
