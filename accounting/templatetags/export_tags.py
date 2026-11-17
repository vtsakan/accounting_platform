"""Export links preserve validated scope and freeze default as-of/year/month."""
from django import template
from django.urls import reverse
register=template.Library()


@register.simple_tag(takes_context=True)
def export_url(context,filetype):
    if filetype not in {'pdf','csv'}:raise ValueError('Unknown export format')
    request=context['request'];form=context['filter_form'];name=request.resolver_match.url_name
    if not form.is_valid():return ''
    route={'summary-report':'report-export','client-statement':'client-statement-export','fees-overview':'fees-overview-export'}[name]
    kwargs={'filetype':filetype}
    if name=='client-statement':kwargs['pk']=context['entity'].pk
    query=request.GET.copy()
    for key in list(query):
        if key not in form.fields or key in {'page','page_size','charge_page','credit_page','event_page'}:query.pop(key,None)
    for key in ('as_of','year','month'):
        if form.cleaned_data.get(key):
            value=form.cleaned_data[key];query[key]=value.isoformat() if key=='as_of' else str(value)
    return reverse(route,kwargs=kwargs)+'?'+query.urlencode()
