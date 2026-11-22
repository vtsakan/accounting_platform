"""Static imports/routes/secret-flow checks only; no application setup."""
import ast
import json
from pathlib import Path

from cr007_static_inputs import target, defines
from cr008_static_inputs import inspect as inspect_attachments, required_call_arguments
from r1_gate import require


def inspect(root):
    root=Path(root).resolve(); prior=inspect_attachments(root); count=0
    paths=[root/'accounting'/n for n in ('gsis_services.py','gsis_views.py','tests_gsis.py')]
    for path in paths:
        for node in ast.parse(path.read_text()).body:
            if not isinstance(node,ast.ImportFrom):continue
            linked=target(root,path,node)
            if not linked:continue
            for alias in node.names:
                require(alias.name!='*' and defines(root,linked,alias.name), 'Unknown GSIS local import: '+alias.name)
                count+=1
    calls=required_call_arguments(root,paths)
    urls=(root/'accounting/urls.py').read_text()
    matrix=json.loads((root/'accounting/office_boundary_matrix.json').read_text())
    rows=[r for r in matrix['routes'] if r['route']=='entity-gsis-credentials']
    require(len(rows)==1 and rows[0]['capability']=='clients.credentials' and rows[0]['methods']==['POST']
        and urls.count("name='entity-gsis-credentials'")==1, 'Declare the exact scoped POST-only GSIS route')
    js=(root/'accounting/static/accounting/workspace/gsis.js').read_text()
    require('https://www1.gsis.gr/taxisnet/mytaxisnet' in js and 'clipboard.writeText' in js
        and 'textContent' in js and '90000' in js and 'pagehide' in js
        and 'credentials: "same-origin"' in js and 'cache: "no-store"' in js
        and 'X-CSRFToken' in js and 'requestGeneration !== generation' in js,
        'Keep the explicit same-origin read/copy/expiry flow')
    require(not any(value in js for value in ('localStorage','sessionStorage','document.cookie','innerHTML',
        'console.','requestSubmit(','.submit(', 'bmctx=', 'request_id=', 'password=', 'username=', 'postMessage(')),
        'GSIS copy cannot store/log secrets, submit externally or put credentials/session tokens in a URL')
    view=(root/'accounting/gsis_views.py').read_text()
    require("@office_view('clients.credentials', mfa=True)" in view and '@require_POST' in view
        and "'no-store, private'" in view and "'no-referrer'" in view, 'Retain MFA, POST and secret response headers')
    template=(root/'accounting/templates/accounting/entity_profile/gsis.html').read_text()
    require('type="password"' in template and template.count('data-gsis-launch')==2
        and '{{ taxis_' not in template and '{% csrf_token %}' in template, 'Two blank-on-GET selected-person controls required')
    for name in ('entity_detail.html','entity_profile/editor.html'):
        require("include 'accounting/entity_profile/gsis.html'" in (root/'accounting/templates/accounting'/name).read_text(),
            'Both the central client card and editor need the GSIS controls')
    return {'local_import_symbols':count,'local_call_arguments_checked':calls,
        'retained_attachment_static_checks':prior,'application_or_tests_executed':False}
