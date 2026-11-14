#!/usr/bin/env python3
"""Create an explicitly illustrative standalone design preview, without Django/DB."""
import argparse
import ast
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def preview():
    tree = ast.parse((ROOT / 'accounting/templatetags/workspace_ui.py').read_text())
    icons = next(ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
                 and any(isinstance(target, ast.Name) and target.id == 'ICONS' for target in node.targets))

    def icon(name):
        paths = ''.join('<path d="' + escape(path, quote=True) + '"></path>' for path in icons[name])
        return '<svg class="ui-icon" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + paths + '</svg>'

    css = (ROOT / 'accounting/static/accounting/workspace/workspace.css').read_text()
    script = (ROOT / 'accounting/static/accounting/workspace/workspace.js').read_text()
    art = (ROOT / 'accounting/templates/accounting/includes/workspace_art.html').read_text().replace(
        '{% if auth_art %}auth-art{% else %}hero-art{% endif %}', 'hero-art')
    groups = [
        ('Η καθημερινότητά σας', [('Επισκόπηση', 'grid'), ('Κινήσεις', 'activity'), ('Ταμεία', 'wallet'), ('Συμφωνίες', 'document'), ('Αναφορά', 'chart')]),
        ('Οι συνεργασίες σας', [('Συναλλασσόμενοι', 'people'), ('Πελάτες', 'person'), ('Προμηθευτές', 'briefcase'), ('Κατηγορίες', 'tag')]),
        ('Οργάνωση &amp; ασφάλεια', [('Γραφείο', 'building'), ('Συνεργάτες', 'people'), ('Ασφάλεια', 'shield')]),
    ]
    navigation = ''
    for heading, links in groups:
        navigation += '<p class="nav-group-label">' + heading + '</p>'
        for label, symbol in links:
            active = label == 'Επισκόπηση'
            navigation += '<a class="workspace-nav-link' + (' is-active' if active else '') + '" href="' + ('#overview' if active else '#preview-note') + '">' + icon(symbol) + '<span>' + label + '</span>' + ('<span class="nav-current-dot"></span>' if active else '') + '</a>'
    stats = ''
    for label, amount, symbol, kind in [('Λειτουργικές εισπράξεις', '6.420,00 €', 'arrow-down', ''), ('Λειτουργικές πληρωμές', '2.180,00 €', 'arrow-up', 'stat-card--expense'), ('Καθαρή λειτουργική ροή', '4.240,00 €', 'activity', 'stat-card--net')]:
        stats += '<article class="stat-card ' + kind + '"><div class="stat-top"><span>' + label + '</span><span class="stat-icon">' + icon(symbol) + '</span></div><strong class="stat-value">' + amount + '</strong><span class="stat-footnote">01/11/2026 — 14/11/2026 · ενδεικτικά στοιχεία</span></article>'
    accounts = ''
    for name, amount, pending in [('Τράπεζα γραφείου', '8.350,00 €', False), ('Μετρητά', '680,00 €', False), ('Νέος λογαριασμός', '', True)]:
        accounts += '<div class="account-tile"><span class="account-icon">' + icon('wallet') + '</span><div class="account-name"><a href="#preview-note">' + name + '</a><small>' + ('Χρειάζεται επιβεβαίωση έναρξης' if pending else 'Υπόλοιπο σήμερα') + '</small></div>' + ('<span class="status-chip">Αναμονή αρχικού υπολοίπου</span>' if pending else '<span class="account-amount">' + amount + '</span>') + '</div>'
    movements = ''
    for description, party, date, amount, incoming in [('Αμοιβή λογιστικών υπηρεσιών', 'Δοκιμαστική εταιρεία Α', '14/11/2026', '350,00 €', True), ('Λειτουργικά έξοδα γραφείου', 'Δοκιμαστικός προμηθευτής', '13/11/2026', '85,00 €', False), ('Είσπραξη συμφωνίας', 'Δοκιμαστική εταιρεία Β', '12/11/2026', '580,00 €', True)]:
        movements += '<tr><td class="recent-description"><strong>' + description + '</strong><small>' + party + '</small></td><td class="text-nowrap">' + date + '</td><td><span class="movement-direction ' + ('text-success' if incoming else 'text-danger') + '">' + icon('arrow-down' if incoming else 'arrow-up') + (' Εισερχόμενα' if incoming else ' Εξερχόμενα') + '</span></td><td class="text-end text-nowrap">' + amount + '</td></tr>'

    def actions(links):
        return ''.join('<a class="quick-action" href="#preview-note">' + icon(symbol) + label + '</a>' for label, symbol in links)

    return f'''<!doctype html><html lang="el"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Προεπισκόπηση σχεδιασμού — Λογιστική πλατφόρμα</title><style>{css}</style></head>
<body class="workspace-body"><a class="skip-link" href="#main-content">Μετάβαση στο κύριο περιεχόμενο</a>
<div class="workspace-shell"><details class="workspace-navigation" id="workspace-navigation" open><summary class="mobile-navigation-toggle">{icon('menu')}<span>Λογιστική πλατφόρμα</span><span class="mobile-navigation-caption">Μενού</span></summary><aside class="workspace-sidebar" aria-label="Πλοήγηση προεπισκόπησης">
<a class="workspace-brand" href="#overview"><span class="brand-mark">λ</span><span><strong>Λογιστική</strong><small>πλατφόρμα γραφείου</small></span></a>
<div class="office-switcher">{icon('building')}<div><span>Χώρος εργασίας</span><strong>Δοκιμαστικό λογιστικό γραφείο</strong></div></div><nav class="workspace-nav" aria-label="Κύρια πλοήγηση">{navigation}</nav>
<div class="sidebar-user"><span class="user-avatar">Δ</span><div><strong>Δοκιμαστικός χρήστης</strong><span>Υπεύθυνος γραφείου</span></div></div></aside></details>
<div class="workspace-stage"><header class="workspace-topbar"><div class="topbar-greeting"><span class="topbar-eyebrow">Προεπισκόπηση σχεδιασμού</span><span>Καλώς ήρθατε, <strong>στο νέο σας γραφείο</strong></span></div><div class="workspace-search">{icon('search')}<input aria-label="Ενδεικτική αναζήτηση" type="search" placeholder="Αναζήτηση συναλλασσομένου…" disabled></div><button class="theme-toggle" type="button" data-theme-toggle aria-label="Ενεργοποίηση σκούρου θέματος" aria-pressed="false" hidden><span class="theme-moon">{icon('moon')}</span><span class="theme-sun">{icon('sun')}</span></button></header>
<main class="workspace-main" id="main-content" tabindex="-1"><div class="alert alert-info" id="preview-note"><strong>Προεπισκόπηση σχεδιασμού · ενδεικτικά δεδομένα.</strong> Αυτό το αρχείο παρουσιάζει την εμφάνιση. Οι λειτουργικές οθόνες, η αναζήτηση και οι καταχωρίσεις βρίσκονται στην εφαρμογή.</div>
<div class="page-heading" id="overview"><div><span class="page-eyebrow">Ο χώρος εργασίας σας</span><h1>Επισκόπηση</h1><p>Μια καθαρή εικόνα, για να ξεκινά κάθε ημέρα οργανωμένα.</p></div><div class="page-date">{icon('clock')}<span>Σάββατο, 14 Νοεμβρίου 2026</span></div></div>
<section class="dashboard-hero"><div class="hero-copy"><span class="hero-eyebrow">{icon('building')} Το γραφείο σας, σε μία ματιά</span><h2>Λιγότερη αναζήτηση.<br><span>Περισσότερη ουσία.</span></h2><p>Οι κινήσεις, τα ταμεία και οι συνεργασίες σας σε έναν οργανωμένο χώρο.</p><div class="hero-actions"><a class="btn btn-primary" href="#preview-note">{icon('plus')} Νέο έσοδο</a><a class="btn btn-outline-secondary" href="#preview-note">Συνοπτική αναφορά {icon('arrow-right')}</a></div></div>{art}</section>
<section class="stats-grid" aria-label="Ενδεικτικά λειτουργικά σύνολα">{stats}</section>
<div class="dashboard-columns"><div><section class="workspace-panel"><div class="panel-heading"><div><h2>Υπόλοιπα ταμείων</h2><p>3 ενεργά ταμεία · ενδεικτικά στοιχεία</p></div><a href="#preview-note">Όλα τα ταμεία {icon('arrow-right')}</a></div><div class="account-stack">{accounts}</div><p class="panel-note">Η λειτουργική ροή και τα ταμειακά υπόλοιπα παρακολουθούνται χωριστά.</p></section>
<section class="workspace-panel"><div class="panel-heading"><div><h2>Πρόσφατες κινήσεις</h2><p>Ενδεικτικές καταχωρίσεις για την παρουσίαση</p></div><a href="#preview-note">Όλες οι κινήσεις {icon('arrow-right')}</a></div><div class="table-responsive"><table class="table recent-table"><caption>Δοκιμαστικά στοιχεία προεπισκόπησης</caption><thead><tr><th scope="col">Κίνηση</th><th scope="col">Ημερομηνία</th><th scope="col">Κατεύθυνση</th><th scope="col" class="text-end">Ποσό</th></tr></thead><tbody>{movements}</tbody></table></div></section></div>
<div><section class="workspace-panel"><div class="panel-heading"><div><h2>Γρήγορες ενέργειες</h2><p>Το επόμενο βήμα, ένα πάτημα μακριά</p></div></div><div class="quick-actions">{actions([('Νέο έσοδο','arrow-down'),('Νέο έξοδο','arrow-up'),('Εσωτερική μεταφορά','handover'),('Νέος συναλλασσόμενος','people')])}</div></section>
<section class="workspace-panel"><div class="panel-heading"><div><h2>Αναφορές και προβολές</h2><p>Από τη σύνοψη στη λεπτομέρεια</p></div></div><div class="quick-actions">{actions([('Συνοπτική αναφορά','chart'),('Συμφωνίες','document'),('Πελάτες','person'),('Προμηθευτές','briefcase')])}</div></section>
<aside class="workspace-note">{icon('info')}<div><strong>Κάθε ποσό έχει τη δική του θέση</strong><p>Η λειτουργική ροή, τα υπόλοιπα και οι χρεώσεις εμφανίζονται χωριστά στην πραγματική εφαρμογή.</p></div></aside></div></div>
</main><footer class="workspace-footer"><span>Λογιστική πλατφόρμα</span><span>Το γραφείο σας. Σε τάξη.</span></footer></div></div><script>{script}</script></body></html>'''


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'private/s24a-design-preview.html')
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(preview())
    print('Illustrative design preview created: ' + str(args.output))
