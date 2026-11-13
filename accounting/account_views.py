"""Greek staff account/category screens with explicit version and owner proof."""
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import DatabaseError
from django.http import Http404
from django.shortcuts import render,redirect
from django.utils import timezone
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods,require_GET
from .account_forms import AccountForm,CategoryForm,StateForm,OpeningForm,AdjustmentForm,BalanceDateForm
from .account_services import save_reference,preview_opening,approve_opening,adjust_opening
from .cash_selectors import cash_accounts
from .capabilities import office_view
from .office_access import record,records
from .models import CashAccount,Category,CashAdjustment,Transaction
from .office_views import validation,budget
from .auth_views import limited


def page_context(request,title,form,**extra):
    return {'title':title,'form':form,**extra}


@office_view('finance.read')
@require_GET
def account_list(request):
    status=request.GET.get('state','all')
    rows=cash_accounts(request.user,include_inactive=True)
    error=''
    if status=='active':rows=rows.filter(is_active=True)
    elif status=='inactive':rows=rows.filter(is_active=False)
    elif status=='pending':rows=rows.filter(opening_date__isnull=True)
    elif status!='all':error='Η επιλογή κατάστασης δεν είναι έγκυρη.';rows=rows.none()
    return render(request,'accounting/cash/accounts.html',{'page':Paginator(rows,25).get_page(request.GET.get('page')),'state':status,'error':error})


@office_view('finance.write')
@require_http_methods(['GET','POST'])
def account_add(request):
    form=AccountForm(request.POST if request.method=='POST' else None)
    if request.method=='POST' and validation(form,lambda d:save_reference(CashAccount(name=d['name'],is_active=d['is_active']),request.user)):
        messages.success(request,'Το ταμείο δημιουργήθηκε σε αναμονή έγκρισης αρχικού υπολοίπου.')
        return redirect('cash-account-list')
    return render(request,'accounting/cash/form.html',page_context(request,'Νέο ταμείο',form,note='Η αρχική ημερομηνία και το ποσό εγκρίνονται χωριστά από τον υπεύθυνο με MFA.'))


@office_view('finance.read')
@require_GET
def account_detail(request,pk):
    account=record(CashAccount,request.user,pk);form=BalanceDateForm(request.GET or None)
    day=timezone.localdate()
    if form.is_bound and form.is_valid():day=form.cleaned_data['as_of']
    account=cash_accounts(request.user,as_of=day,include_inactive=True).get(pk=account.pk)
    history=records(Transaction,request.user).filter(cash_account=account).select_related('entity','category').order_by('-transaction_date','-pk')
    adjustments=CashAdjustment.objects.filter(office_id=account.office_id,account=account).select_related('actor','reversal_of').order_by('-effective_date','-pk')[:50]
    return render(request,'accounting/cash/detail.html',{'account':account,'form':form,'day':day,
        'page':Paginator(history,25).get_page(request.GET.get('page')),'adjustments':adjustments})


@office_view('finance.write')
@require_http_methods(['GET','POST'])
def account_edit(request,pk):
    account=record(CashAccount,request.user,pk)
    form=AccountForm(request.POST if request.method=='POST' else None,initial={'name':account.name,'is_active':account.is_active,'version':account.record_version})
    def save(data):
        account.name=data['name'];account.is_active=data['is_active']
        return save_reference(account,request.user,expected_version=data['version'])
    if request.method=='POST' and validation(form,save):return redirect('cash-account-detail',pk=pk)
    return render(request,'accounting/cash/form.html',page_context(request,'Στοιχεία ταμείου',form,note='Η απενεργοποίηση διατηρεί όλες τις κινήσεις και το ιστορικό.'))


@office_view('finance.opening',mfa=True)
@sensitive_post_parameters('password','review_token')
@require_http_methods(['GET','POST'])
def account_opening(request,pk):
    account=record(CashAccount,request.user,pk);request.session['s13_next']=request.path
    form=OpeningForm(request.POST if request.method=='POST' else None,initial={'amount':account.opening_balance})
    proposal=None
    if request.method=='POST':
        if not budget(request):return limited(request)
        if form.is_valid():
            data=form.cleaned_data
            try:
                if request.POST.get('action')=='confirm':
                    approve_opening(request,account_id=pk,review_token=data['review_token'],amount=data['amount'],effective_date=data['effective_date'],
                        reason=data['reason'],review_reference=data['review_reference'],password=data['password'],idempotency_key=str(data['idempotency_key']),acknowledged=data['acknowledged'])
                    messages.success(request,'Το αρχικό υπόλοιπο και η ημερομηνία εγκρίθηκαν.')
                    return redirect('cash-account-detail',pk=pk)
                proposal,token=preview_opening(request.user,account_id=pk,amount=data['amount'],effective_date=data['effective_date'])
                values=request.POST.copy();values['review_token']=token;values['password']='';form=OpeningForm(values)
            except ValidationError as error:form.add_error(None,error)
            except DatabaseError as error:
                if getattr(error.__cause__,'sqlstate',None) not in {'23505','23514','40001','40P01'}:raise
                form.add_error(None,'Τα στοιχεία άλλαξαν ή παραβιάζεται κανόνας αρχικού υπολοίπου. Δημιουργήστε νέα προεπισκόπηση.')
    return render(request,'accounting/cash/opening.html',{'account':account,'form':form,'proposal':proposal})


@office_view('finance.opening',mfa=True)
@sensitive_post_parameters('password')
@require_http_methods(['GET','POST'])
def account_adjustment(request,pk):
    account=record(CashAccount,request.user,pk);request.session['s13_next']=request.path
    original=None;key=request.POST.get('reversal_of_id') if request.method=='POST' else request.GET.get('reverse')
    if key:
        try:original=CashAdjustment.objects.filter(pk=int(key),office_id=account.office_id,account=account).first()
        except (ValueError,TypeError):original=None
        if original is None:raise Http404('Η προσαρμογή δεν βρέθηκε στο ταμείο.')
    form=AdjustmentForm(request.POST if request.method=='POST' else None,initial={'reversal_of_id':original.pk if original else None})
    def apply(data):
        return adjust_opening(request,account_id=pk,amount=data['amount'],effective_date=data['effective_date'],reason=data['reason'],
            review_reference=data['review_reference'],password=data['password'],idempotency_key=str(data['idempotency_key']),reversal_of_id=original.pk if original else None)
    if request.method=='POST':
        if not budget(request):return limited(request)
        if validation(form,apply):
            messages.success(request,'Η προσαρμογή καταχωρίστηκε με διατήρηση του αρχικού υπολοίπου.')
            return redirect('cash-account-detail',pk=pk)
    return render(request,'accounting/cash/form.html',page_context(request,'Αντιλογισμός προσαρμογής' if original else 'Προσαρμογή αρχικού υπολοίπου',form,
        note='Απαιτείται έλεγχος αρχικού υπολοίπου, κωδικός πρόσβασης και MFA των τελευταίων πέντε λεπτών. Δεν πρόκειται για έσοδο ή έξοδο.',original=original))


@office_view('finance.read')
@require_GET
def category_list(request):
    rows=records(Category,request.user).select_related('parent').order_by('name','pk')
    return render(request,'accounting/cash/categories.html',{'page':Paginator(rows,25).get_page(request.GET.get('page'))})


def category_editor(request,pk=None):
    category=record(Category,request.user,pk) if pk else Category()
    initial={'name':category.name,'parent':category.parent_id,'is_active':category.is_active,'version':category.record_version}
    form=CategoryForm(request.POST if request.method=='POST' else None,user=request.user,instance=category if pk else None,initial=initial)
    def save(data):
        category.name=data['name'];category.parent=data['parent'];category.is_active=data['is_active']
        return save_reference(category,request.user,expected_version=data['version'])
    if request.method=='POST' and validation(form,save):return redirect('category-list')
    return render(request,'accounting/cash/form.html',page_context(request,'Στοιχεία κατηγορίας' if pk else 'Νέα κατηγορία',form,
        note='Η αλλαγή ονόματος δεν αλλάζει τα καταχωρισμένα ποσά. Η απόσυρση διατηρεί το ιστορικό.'))

@office_view('finance.write')
@require_http_methods(['GET','POST'])
def category_add(request):return category_editor(request)

@office_view('finance.write')
@require_http_methods(['GET','POST'])
def category_edit(request,pk):return category_editor(request,pk)

@office_view('finance.write')
@require_http_methods(['GET','POST'])
def category_retire(request,pk):
    category=record(Category,request.user,pk)
    form=StateForm(request.POST if request.method=='POST' else None,initial={'version':category.record_version,'active':not category.is_active})
    def save(data):
        category.is_active=data['active'];return save_reference(category,request.user,expected_version=data['version'])
    if request.method=='POST' and validation(form,save):return redirect('category-list')
    return render(request,'accounting/cash/form.html',page_context(request,'Απόσυρση κατηγορίας' if category.is_active else 'Επαναφορά κατηγορίας',form,
        note='Η κατηγορία και οι κινήσεις της διατηρούνται. Οι ενεργές υποκατηγορίες πρέπει πρώτα να μετακινηθούν ή να αποσυρθούν.'))
