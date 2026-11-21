"""Greek finance.read reporting; screen and future exports share selectors."""
from django.shortcuts import get_object_or_404,render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET
from .capabilities import office_view,require_capability
from .models import Entity
from .office_access import record, validate_filter_ids
from .report_forms import PeriodReportForm,StatementForm,AnnualReportForm
from .report_selectors import period_report,annual_report,dashboard_report


@office_view('finance.read')
@never_cache
@require_GET
def overview(request):
    return render(request,'accounting/dashboard.html',dashboard_report(request.user))


@office_view('finance.read')
@never_cache
@require_GET
def period(request):
    validate_filter_ids(request)
    form=PeriodReportForm(request.GET,user=request.user)
    return render(request,'accounting/summary_report.html',{'filter_form':form,**period_report(request.user,form)})


@office_view('finance.read')
@never_cache
@require_GET
def statement(request,pk):
    validate_filter_ids(request)
    entity=record(Entity,request.user,pk)
    form=StatementForm(request.GET,user=request.user,entity=entity)
    return render(request,'accounting/reports/statement.html',{'filter_form':form,'entity':entity,**period_report(request.user,form,statement=True)})


@office_view('finance.read')
@never_cache
@require_GET
def annual(request):
    validate_filter_ids(request)
    form=AnnualReportForm(request.GET,user=request.user)
    return render(request,'accounting/reports/annual.html',{'filter_form':form,**annual_report(request.user,form)})
