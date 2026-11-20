"""Greek catalogue, schedule history and non-posting period preview."""
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import DatabaseError, transaction
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods
from .capabilities import office_view, require_capability
from .fee_forms import PriceForm, ScheduleForm, ScheduleChangeForm, PreviewForm
from .fee_models import ServiceItem
from .fee_services import catalogue, price_on, save_price, schedules, create_schedule, change_schedule, preview
from .office_access import locked_office


def failed(form, error):
    if isinstance(error, DatabaseError):
        if getattr(error.__cause__, 'sqlstate', None) not in {'23505','23514','23503','40001','40P01'}:
            raise error
        form.add_error(None, 'Η ενέργεια δεν ολοκληρώθηκε. Ανανεώστε τα στοιχεία πριν επαναλάβετε.')
    else:
        form.add_error(None, ' '.join(error.messages))


def owner(user):
    return require_capability(user, 'finance.read').role == 'owner'


@office_view('finance.read')
@never_cache
@require_http_methods(['GET'])
def catalogue_list(request):
    page = Paginator(catalogue(request.user), 25).get_page(request.GET.get('page'))
    rows = [{'service':s, 'price':price_on(s)} for s in page]
    return render(request, 'accounting/fees/catalogue.html', {'rows':rows, 'page':page, 'can_manage':owner(request.user)})


@office_view('office.settings')
@never_cache
@require_http_methods(['GET','POST'])
def price_edit(request, key=None):
    service = get_object_or_404(catalogue(request.user), pk=key) if key else None
    latest = service.prices.first() if service else None
    initial = {'expected_revision':latest.revision, 'description':latest.description, 'amount':latest.amount,
        'effective_date':max(latest.effective_date, timezone.localdate()), 'is_active':latest.is_active} if latest else {}
    form = PriceForm(request.POST if request.method == 'POST' else None, service=service, initial=initial)
    if request.method == 'POST' and form.is_valid():
        try:
            price = save_price(request.user, service_id=service.pk if service else None, **form.cleaned_data)
        except (ValidationError, DatabaseError) as error:
            failed(form, error)
        else:
            messages.success(request, 'Η νέα έκδοση τιμής αποθηκεύτηκε. Οι παλιές συμφωνίες και χρεώσεις διατηρούνται.')
            return redirect('service-price-edit', key=price.service_id)
    return render(request, 'accounting/fees/form.html', {'form':form, 'title':'Ιστορικό τιμής υπηρεσίας' if service else 'Νέα υπηρεσία',
        'history':service.prices.all() if service else [], 'catalogue':True})


@office_view('finance.write')
@never_cache
@require_http_methods(['GET','POST'])
def agreement_from_service(request, key):
    """Copy a current immutable quote into a reviewed agreement, never cash."""
    from .agreement_creation_forms import AgreementCreationForm
    service = get_object_or_404(catalogue(request.user), pk=key)
    price = price_on(service)
    if price is None or not price.is_active:
        return render(request, 'accounting/fees/unavailable.html', status=409)
    initial = {'description':price.description, 'total_amount':price.amount, 'start_date':timezone.localdate(),
        'agreement_type':'RECEIVABLE', 'billing_mode':'MONTHLY', 'lifecycle':'ACTIVE', 'status':'ACTIVE'}
    form = AgreementCreationForm(request.POST if request.method == 'POST' else None, user=request.user, initial=initial)
    form.fields['reason'].max_length = 350
    if request.method == 'POST' and form.is_valid():
        try:
            with transaction.atomic():
                locked_office(request.user, 'finance.write')
                fresh = price_on(service)
                if not fresh or not fresh.is_active or len(request.POST.getlist('price_version')) != 1 or str(fresh.pk) != request.POST.get('price_version'):
                    raise ValidationError('Η τιμή υπηρεσίας άλλαξε. Ελέγξτε τη νέα προσφορά πριν αποθηκεύσετε.')
                if form.cleaned_data['billing_mode'] != 'MONTHLY' or form.cleaned_data['agreement_type'] != 'RECEIVABLE' or form.cleaned_data['lifecycle'] != 'ACTIVE':
                    raise ValidationError('Αυτή η διαδικασία δημιουργεί ενεργή μηνιαία εισπρακτέα συμφωνία.')
                if len(form.cleaned_data['reason'] or '') > 350:
                    raise ValidationError('Η αιτιολογία από τιμοκατάλογο έχει έως 350 χαρακτήρες.')
                form.cleaned_data['reason'] = f'Τιμοκατάλογος {service.code}, έκδοση {fresh.revision}. ' + (form.cleaned_data['reason'] or 'Επιβεβαίωση περιγραφής και μικτής αμοιβής')
                agreement = form.save()
        except (ValidationError, DatabaseError) as error:
            failed(form, error)
        else:
            messages.success(request, 'Η συμφωνία και η πρώτη μηνιαία χρέωση καταχωρίστηκαν. Συνεχίστε με το πρόγραμμα των επόμενων μηνών.')
            return redirect('fee-schedule-add')
    return render(request, 'accounting/fees/agreement.html', {'form':form, 'service':service, 'price':price})


@office_view('finance.read')
@never_cache
@require_http_methods(['GET'])
def schedule_list(request):
    page = Paginator(schedules(request.user), 25).get_page(request.GET.get('page'))
    return render(request, 'accounting/fees/schedules.html', {'rows':page, 'page':page})


@office_view('finance.write')
@never_cache
@require_http_methods(['GET','POST'])
def schedule_add(request):
    form = ScheduleForm(request.POST if request.method == 'POST' else None, user=request.user,
        initial={'start_period':timezone.localdate().strftime('%Y-%m')})
    if request.method == 'POST' and form.is_valid():
        data = dict(form.cleaned_data);data['agreement_id'] = data.pop('agreement').pk
        try:
            schedule = create_schedule(request.user, **data)
        except (ValidationError, DatabaseError) as error:
            failed(form, error)
        else:
            messages.success(request, 'Το πρόγραμμα αποθηκεύτηκε. Δεν καταχωρίστηκε χρέωση ή είσπραξη.')
            return redirect('fee-schedule-detail', key=schedule.pk)
    return render(request, 'accounting/fees/form.html', {'form':form, 'title':'Νέο μηνιαίο πρόγραμμα', 'history':[]})


@office_view('finance.read')
@never_cache
@require_http_methods(['GET'])
def schedule_detail(request, key):
    schedule = get_object_or_404(schedules(request.user), pk=key)
    form = PreviewForm(request.GET if request.GET else None, initial={'months':12})
    rows = []
    if not request.GET or form.is_valid():
        try:
            rows = preview(request.user, key, **(form.cleaned_data if request.GET else {}))
        except ValidationError as error:
            form.add_error(None, ' '.join(error.messages))
    return render(request, 'accounting/fees/detail.html', {'schedule':schedule, 'form':form, 'rows':rows,
        'versions':schedule.versions.select_related('actor','terms_snapshot'), 'can_manage':owner(request.user)})


@office_view('finance.amend', mfa=True)
@never_cache
@sensitive_post_parameters('password','reason')
@require_http_methods(['GET','POST'])
def schedule_change(request, key):
    schedule = get_object_or_404(schedules(request.user), pk=key)
    latest = schedule.versions.first()
    form = ScheduleChangeForm(request.POST if request.method == 'POST' else None, initial={'expected_revision':latest.revision,
        'due_day':latest.due_day, 'due_next_month':latest.due_next_month,
        'end_period':latest.end_period.strftime('%Y-%m') if latest.end_period else ''})
    if request.method == 'POST' and form.is_valid():
        try:
            change_schedule(request, schedule_id=key, **form.cleaned_data)
        except (ValidationError, DatabaseError) as error:
            failed(form, error)
        else:
            messages.success(request, 'Η μελλοντική αλλαγή προγράμματος καταγράφηκε. Οι χρεώσεις διατηρούνται.')
            return redirect('fee-schedule-detail', key=key)
    return render(request, 'accounting/fees/form.html', {'form':form, 'title':'Μελλοντική αλλαγή ή διακοπή προγράμματος', 'history':[]})
