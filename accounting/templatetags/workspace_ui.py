"""Local presentation primitives; no queries or permission decisions."""
from django import template
from django.utils.html import format_html, format_html_join

register = template.Library()

# Original SVG strokes, with no remote icon font or client-side loader.
ICONS = {
    'grid': ('M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z',),
    'activity': ('M3 12h4l3-8 4 16 3-8h4',),
    'wallet': ('M20 8V5a2 2 0 0 0-2-2H6a3 3 0 0 0 0 6h14v11H6a3 3 0 0 1-3-3V6', 'M20 12h-5v5h5M16 14.5h.01'),
    'people': ('M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M16 4a4 4 0 0 1 0 8M22 21v-2a4 4 0 0 0-3-3.87', 'M13 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0'),
    'person': ('M20 21v-2a7 7 0 0 0-14 0v2', 'M17 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0'),
    'briefcase': ('M3 7h18v14H3zM8 7V3h8v4M3 12a23 23 0 0 0 18 0M10 12v4h4v-4',),
    'document': ('M14 2H5v20h14V7zM14 2v5h5M8 12h8M8 16h6',),
    'chart': ('M3 3v18h18M7 16v-5M12 16V7M17 16v-8',),
    'tag': ('M20 13 13 20 3 10V3h7zM7 7h.01',),
    'shield': ('M12 3 3 7v5c0 5 9 10 9 10s9-5 9-10V7zM8 12l3 3 5-6',),
    'building': ('M4 21V3h12v18M16 9h4v12M8 7h4M8 11h4M8 15h4M9 21v-3h2v3M2 21h20',),
    'handover': ('M3 8h14l-4-4M17 8l-4 4M21 16H7l4-4M7 16l4 4',),
    'arrow-up': ('M7 17 17 7M7 7h10v10',),
    'arrow-down': ('m7 7 10 10M7 17h10V7',),
    'arrow-right': ('M4 12h16m-6-6 6 6-6 6',),
    'plus': ('M12 5v14M5 12h14',),
    'search': ('M21 21l-5-5', 'M18 10a7 7 0 1 1-14 0 7 7 0 0 1 14 0'),
    'logout': ('M9 3H3v18h6M9 12h12m-5-5 5 5-5 5',),
    'moon': ('M21 13A9 9 0 0 1 11 3 9 9 0 1 0 21 13',),
    'sun': ('M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4', 'M16 12a4 4 0 1 1-8 0 4 4 0 0 1 8 0'),
    'menu': ('M4 6h16M4 12h16M4 18h16',),
    'clock': ('M12 7v5l3 2', 'M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0'),
    'check': ('m5 12 4 4L19 6',),
    'info': ('M12 11v6M12 7h.01', 'M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0'),
}

NAV_GROUPS = {
    'dashboard': {'dashboard'},
    'transaction-list': {'transaction-list', 'add-income', 'add-expense', 'add-transfer', 'cash-correction', 'cash-refund', 'finance-correction-history', 'finance-period-close'},
    'cash-account-list': {'cash-account-list', 'cash-account-add', 'cash-account-detail', 'cash-account-edit', 'cash-account-opening', 'cash-account-adjustment'},
    'category-list': {'category-list', 'category-add', 'category-edit', 'category-retire'},
    'agreement-list': {'agreement-list', 'agreement-detail', 'add-agreement', 'edit-agreement', 'agreement-charge-add', 'agreement-amend', 'charge-correction'},
    'counterparty-list': {'counterparty-list', 'add-entity', 'entity-detail', 'edit-entity', 'archive-entity', 'restore-entity', 'entity-settlements', 'cash-allocation-add', 'allocation-release'},
    'customer-list': {'customer-list'}, 'supplier-list': {'supplier-list'}, 'summary-report': {'summary-report'},
    'security-settings': {'security-settings', 'mfa-setup', 'mfa-verify', 'mfa-recover'},
    'office-settings': {'office-settings'},
    'office-members': {'office-members', 'office-member-action', 'office-invitation-action'},
    'office-audit': {'office-audit'}, 'office-ownership': {'office-ownership', 'office-handover-detail'},
}


@register.simple_tag
def ui_icon(name):
    paths = format_html_join('', '<path d="{}"></path>', ((path,) for path in ICONS.get(name, ICONS['grid'])))
    return format_html('<svg class="ui-icon" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">{}</svg>', paths)


@register.simple_tag
def ui_nav_active(current_route, destination):
    return current_route in NAV_GROUPS.get(destination, {destination})
