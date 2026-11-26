"""Static imports, calls, authority and first-login control review; no app setup."""
import ast
import builtins
import json
from pathlib import Path
import symtable

from cr007_static_inputs import defines,target
from cr008_static_inputs import required_call_arguments
from cr010_static_inputs import inspect as retained_inspect
from r1_gate import require


def inspect(root):
    root=Path(root).resolve();retained=retained_inspect(root);imports=0
    files=[*sorted((root/'accounting').glob('staff_access*.py')),root/'accounting/tests_direct_staff.py']
    mail_imports=[node for node in ast.parse((root/'accounting/tests_direct_staff.py').read_text()).body
        if isinstance(node,ast.ImportFrom) and any(alias.name=='mail' for alias in node.names)]
    require(len(mail_imports)==1 and mail_imports[0].module=='django.core' and mail_imports[0].level==0,
        'The real Django mail package is django.core.mail; test discovery must not import django.contrib.mail')
    support=next(n for n in ast.parse((root/'accounting/tests_direct_staff.py').read_text()).body
        if isinstance(n,ast.ClassDef) and n.name=='DirectStaffSupport')
    snapshot=next(n for n in support.body if isinstance(n,ast.FunctionDef) and n.name=='snapshot')
    snapshot_source=ast.unparse(snapshot)
    require('OfficeAuditEvent.objects.filter(target_user=user)' in snapshot_source
        and ".order_by('pk').values()" in snapshot_source and 'OfficeAuditEvent.objects.count()' not in snapshot_source,
        'An identity snapshot must compare exact target audit rows, not a global counter changed by another user')
    for path in files:
        text=path.read_text();tree=ast.parse(text)
        table=symtable.symtable(text,str(path),'exec');known=set(table.get_identifiers())|set(dir(builtins))|{'__name__','__file__','__package__'}
        def walk(scope):
            for symbol in scope.get_symbols():
                require(not(symbol.is_referenced() and symbol.is_global() and symbol.get_name() not in known),
                    'Unknown global: '+path.name+':'+symbol.get_name())
            for child in scope.get_children():walk(child)
        walk(table)
        for node in tree.body:
            if not isinstance(node,ast.ImportFrom):continue
            linked=target(root,path,node)
            if not linked:continue
            for alias in node.names:
                require(alias.name!='*' and defines(root,linked,alias.name),'Unknown CR011 import: '+path.name+':'+alias.name)
                imports+=1
    services=(root/'accounting/staff_access_services.py').read_text()
    require(services.count('@transaction.atomic')==3 and services.count('prove_actor(request,')==2
        and services.count('owner_not_pending(request.user)')==2 and 'lock_identifiers(' in services
        and 'version != current' in services and 'password_validation.validate_password' in services,
        'Fresh owner proof, serialized identifiers, versions and password validation are required')
    tree=ast.parse(services)
    calls={ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n,ast.Call)}
    require(not any(n.endswith(('send_mail','send_messages','post_charge','post_cash','delete','clear')) for n in calls),
        'Credential operations cannot send email, post money or erase MFA')
    middleware=(root/'accounting/auth_middleware.py').read_text()
    require(middleware.index("if password_change_required(request.user):")<middleware.index('if request.path.startswith("/auth/"):'),
        'Forced change must precede the general authentication route exception')
    require("if password_change_required(self.request.user):" in (root/'accounting/auth_views.py').read_text(),
        'Temporary login must land on mandatory password change before MFA')
    view=(root/'accounting/staff_access_views.py').read_text()
    require('update_session_auth_hash(request,user)' in view and 'django_otp.DEVICE_ID_SESSION_KEY' in view
        and "bind_session(request,state,new_login=True)" in view and "requires_mfa(user,state)" in view,
        'Personal change must rotate the session and then retain normal MFA requirements')
    migration=(root/'accounting/migrations/0039_staff_access.py').read_text()
    require('CreateModel(' in migration and 'RunPython' not in migration and 'AddField' not in migration,
        'The additive empty table cannot mutate existing people or hashes')
    sql=(root/'accounting/migrations/0040_staff_access_guards.py').read_text()
    require('cr011_target_office' in sql and 'cr011_issuer_office' in sql and 'clock_timestamp()' in sql
        and 'actual_revision IS DISTINCT FROM NEW.security_revision' in sql and 'NEW.version<>OLD.version+1' in sql,
        'Database guard must bind office, password marker, server clock and security version')
    matrix={r['route']:r for r in json.loads((root/'accounting/office_boundary_matrix.json').read_text())['routes']}
    for name in ('staff-direct-create','staff-direct-reset'):
        require(matrix[name]['capability']=='staff.manage' and matrix[name]['methods']==['GET','POST'], 'Declare owner-only direct credential route')
    require(matrix['password-change-required']['realm']=='identity-or-recipient-proof'
        and matrix['password-change-required']['capability'] is None,'Required password change is an identity operation')
    return {'local_import_symbols':imports,'local_calls_checked':required_call_arguments(root,files),
        'retained_cr010_checks':retained,'application_or_tests_executed':False}
