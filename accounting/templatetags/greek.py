from django import template
from django.utils.translation import gettext

from core.locale import format_euro, greek_date

register = template.Library()


@register.filter
def euro(value):
    return format_euro(value)


@register.filter
def el_date(value):
    return greek_date(value) if value else "—"


@register.filter
def greek_label(value):
    return gettext(str(value))
