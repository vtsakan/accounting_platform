"""Greek task forms; office, author, recorded clock and status are never inputs."""
import uuid

from django import forms

from .counterparty_journal_forms import NoteForm
from .counterparty_note_services import note_text
from .client_task_selectors import active_members, tasks_installed, today


class TaskFields(forms.Form):
    request_key = forms.UUIDField(widget=forms.HiddenInput, label='Αναγνωριστικό υποβολής',
        error_messages={'required': 'Ανανεώστε τη φόρμα και δοκιμάστε ξανά.', 'invalid': 'Ανοίξτε νέα φόρμα πριν υποβάλετε ξανά.'})
    body = forms.CharField(label='Περιγραφή εργασίας', max_length=5000,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 5}))
    due_date = forms.DateField(label='Ημερομηνία λήξης', input_formats=['%Y-%m-%d', '%d/%m/%Y'],
        widget=forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date', 'min': '1900-01-01', 'max': '2200-12-31', 'class': 'form-control'}))
    assignee = forms.ModelChoiceField(queryset=None, label='Ανάθεση σε', widget=forms.Select(attrs={'class': 'form-select'}))

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['request_key'].initial = uuid.uuid4
        self.fields['assignee'].queryset = active_members(user)
        self.fields['assignee'].initial = user.pk

    def clean_body(self):
        return note_text(self.cleaned_data['body'])

    def clean_due_date(self):
        from .client_task_services import deadline
        return deadline(self.cleaned_data['due_date'])


class TaskEditForm(TaskFields):
    version = forms.IntegerField(min_value=0, widget=forms.HiddenInput, label='Έκδοση εργασίας')


class TaskActionForm(forms.Form):
    request_key = forms.UUIDField(widget=forms.HiddenInput, label='Αναγνωριστικό υποβολής',
        error_messages={'required': 'Ανανεώστε τη φόρμα και δοκιμάστε ξανά.', 'invalid': 'Ανοίξτε νέα φόρμα πριν υποβάλετε ξανά.'})
    version = forms.IntegerField(min_value=0, widget=forms.HiddenInput, label='Έκδοση εργασίας')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['request_key'].initial = uuid.uuid4


class WorkNoteForm(NoteForm):
    as_task = forms.BooleanField(required=False, label='Να γίνει εργασία',
        widget=forms.CheckboxInput(attrs={'data-task-switch': '', 'aria-controls': 'note-task-fields'}))
    recorded_on = forms.DateField(label='Ημερομηνία καταγραφής εργασίας', disabled=True, required=False,
        widget=forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date', 'class': 'form-control'}))
    due_date = forms.DateField(required=False, label='Ημερομηνία λήξης', input_formats=['%Y-%m-%d', '%d/%m/%Y'],
        widget=forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date', 'min': '1900-01-01', 'max': '2200-12-31', 'class': 'form-control'}))
    assignee = forms.ModelChoiceField(queryset=None, required=False, label='Ανάθεση σε', widget=forms.Select(attrs={'class': 'form-select'}))

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.fields['recorded_on'].initial = today
        self.fields['assignee'].queryset = active_members(user)
        self.fields['assignee'].initial = user.pk

    def clean(self):
        values = super().clean()
        if values.get('as_task'):
            if not values.get('due_date'):
                self.add_error('due_date', 'Συμπληρώστε την ημερομηνία λήξης της εργασίας.')
            else:
                from .client_task_services import deadline
                try:
                    deadline(values['due_date'])
                except forms.ValidationError as error:
                    self.add_error('due_date', error.error_dict['due_date'])
            if not values.get('assignee') and 'assignee' not in self.errors:
                # An omitted choice means the current user, not an untrusted ID.
                values['assignee'] = self.user
        else:
            values['due_date'] = None; values['assignee'] = None
        return values


def note_form(user, data=None, *, as_task=False):
    if not tasks_installed():
        return NoteForm(data)
    return WorkNoteForm(data, user=user, initial={'as_task': as_task})


class TaskFilterForm(forms.Form):
    status = forms.ChoiceField(required=False, label='Κατάσταση', choices=[('OPEN', 'Ανοιχτές'), ('DONE', 'Ολοκληρωμένες'), ('ALL', 'Όλες')], widget=forms.Select(attrs={'class': 'form-select'}))

    def __init__(self, data=None, **kwargs):
        values = data.copy() if data is not None else {}
        if not values.get('status'):
            values['status'] = 'OPEN'
        super().__init__(values, **kwargs)
