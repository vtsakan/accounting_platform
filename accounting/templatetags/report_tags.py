"""Pagination keeps validated report filters and the other detail pages."""
from django import template
register=template.Library()


@register.simple_tag(takes_context=True)
def report_page(context,field,number):
    if field not in {'page','charge_page','credit_page','event_page','month'}:
        raise ValueError('Unsupported report page selector')
    query=context['request'].GET.copy()
    form=context.get('filter_form')
    if form and hasattr(form,'cleaned_data'):
        values=form.cleaned_data
        if values.get('as_of'):query['as_of']=values['as_of'].isoformat()
        if values.get('year'):query['year']=str(values['year'])
    query[field]=str(number)
    if field=='month':
        for key in ('page','charge_page','credit_page'):query.pop(key,None)
    return '?'+query.urlencode()
