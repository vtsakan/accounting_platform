"""Static CR012 integration review; no application, tests or database execution."""
import ast
import builtins
import json
from pathlib import Path
import symtable
from types import SimpleNamespace

from cr007_static_inputs import defines,target
from cr008_static_inputs import required_call_arguments
from cr011_static_inputs import inspect as retained_inspect
from r1_gate import require

FILES=('agreement_budget.py','finance_validation.py','cash_charge_models.py','cash_charge_services.py',
    'cash_entry_forms.py','cash_entry_selectors.py','charge_models.py','charge_services.py','correction_services.py',
    'manual_agreement_creation.py','agreement_creation_forms.py','forms.py','movement_views.py','charge_views.py',
    'tests_demand_charges.py','tests_charge_cash.py','tests_demand_migration.py')
TOOLS=('cr012_receipts.py','cr012_runtime_probe.py','cr012_files_gate.py','cr012_delivery_resume.py','run_cr012_tool_guards.py','verify_cr012.py')


def literal_assignment(path,name):
    tree=ast.parse(Path(path).read_text())
    return next(n.value for n in tree.body if isinstance(n,ast.Assign) and any(getattr(t,'id',None)==name for t in n.targets))


def resolved_sql(root):
    """Resolve only reviewed string literals/replace calls, never import migrations."""
    root=Path(root);directory=root/'accounting/migrations'
    old=ast.literal_eval(literal_assignment(directory/'0016_agreement_charge_guards.py','FORWARD'))
    def old_function(module,name):
        require(module=='0016_agreement_charge_guards','Unexpected SQL source')
        start=old.index('CREATE FUNCTION '+name+'(');end=old.index('END $$;',start)+7
        return old[start:end].replace('CREATE FUNCTION','CREATE OR REPLACE FUNCTION',1)
    def value(node,environment):
        if isinstance(node,ast.Constant):return node.value
        if isinstance(node,ast.Name):return environment[node.id]
        if isinstance(node,ast.BinOp) and isinstance(node.op,ast.Add):return value(node.left,environment)+value(node.right,environment)
        if isinstance(node,ast.Attribute):
            parent=value(node.value,environment)
            require(node.attr in {'replace','NEW_CHARGE','old_function'},'Unexpected static SQL attribute')
            return getattr(parent,node.attr)
        if isinstance(node,ast.Call):
            require(not node.keywords,'Unexpected SQL call keywords')
            return value(node.func,environment)(*[value(arg,environment) for arg in node.args])
        raise RuntimeError('Only reviewed literal SQL assembly is allowed')
    charge=value(literal_assignment(directory/'0020_financial_correction_guards.py','NEW_CHARGE'),
        {'OLD_CHARGE':old_function('0016_agreement_charge_guards','accounting_s22_charge_guard')})
    environment={'previous':SimpleNamespace(NEW_CHARGE=charge,old_function=old_function)}
    path=directory/'0042_demand_charge_guards.py'
    for name in ('OLD_SNAPSHOT','SNAPSHOT','OLD_CHARGE','CHARGE','FORWARD','REVERSE'):
        environment[name]=value(literal_assignment(path,name),environment)
    require(environment['SNAPSHOT'].count("'ON_DEMAND'")==1
        and environment['CHARGE'].count("terms.billing_mode='ON_DEMAND'")==1
        and 'IF TG_OP=\'INSERT\' AND NEW.source_key LIKE \'correction:%\'' in environment['CHARGE'],
        'Preserve the original retained correction source and explicit demand choice')
    return environment['FORWARD'],environment['REVERSE']


def inspect(root):
    root=Path(root).resolve();retained=retained_inspect(root);imports=0
    paths=[root/'accounting'/name for name in FILES]+[root/'tools'/name for name in TOOLS]
    for path in paths:
        text=path.read_text();tree=ast.parse(text);table=symtable.symtable(text,str(path),'exec')
        known=set(table.get_identifiers())|set(dir(builtins))|{'__name__','__file__','__package__'}
        def check(scope):
            for symbol in scope.get_symbols():
                require(not(symbol.is_global() and symbol.is_referenced() and symbol.get_name() not in known),
                    'Unknown CR012 global: '+path.name+':'+symbol.get_name())
            for child in scope.get_children():check(child)
        check(table)
        for node in ast.walk(tree):
            if not isinstance(node,ast.ImportFrom):continue
            linked=target(root,path,node)
            if not linked:continue
            for alias in node.names:
                require(alias.name!='*' and defines(root,linked,alias.name),'Unknown CR012 import: '+path.name+':'+alias.name)
                imports+=1
    service=(root/'accounting/cash_charge_services.py').read_text()
    require('@transaction.atomic' in service and "locked_office(user,'finance.write')" in service
        and 'allocated=min(amount,capacity)' in service and "lines=[{'charge':key,'amount':allocated}]" in service
        and 'CashChargeSelection.objects.create' in service and "if original:" in service,
        'One chosen charge, immutable retry binding and atomic excess-credit posting are required')
    matrix={r['route']:r for r in json.loads((root/'accounting/office_boundary_matrix.json').read_text())['routes']}
    require(matrix['cash-charge-options']=={'route':'cash-charge-options','realm':'office-business','capability':'finance.write','methods':['GET']},
        'Declare the scoped read-only dependent charge route')
    forward,reverse=resolved_sql(root)
    require("billing_mode IN ('ONE_OFF','ON_DEMAND')" in forward and 'UNION SELECT r.effective_date' in forward
        and 'proposed_limit' in forward and 'FOR UPDATE' in forward and 'cashchargeselection' in reverse,
        'Real dated gross-charge budgets and retained selection history are required')
    gate=(root/'tools/cr012_files_gate.py').read_text()
    for version in ('008','010','011','012'):
        require('tools/cr'+version+'_runtime_probe.py' in gate and ':/app/cr'+version+'_probe.py:ro' in gate,
            'Mount every retained real native probe dependency')
    probe=ast.parse((root/'tools/cr012_runtime_probe.py').read_text())
    require(any(isinstance(n,ast.Call) and ast.unparse(n.func)=='previous.ProbeClient' for n in ast.walk(probe))
        and not any(isinstance(n,ast.Call) and ast.unparse(n.func)=='Client' for n in ast.walk(probe)),
        'The production file probe must use the real HTTPS/allowed-host MFA client')
    client=next(n for n in ast.parse((root/'tools/cr011_runtime_probe.py').read_text()).body if isinstance(n,ast.ClassDef) and n.name=='ProbeClient')
    body=ast.unparse(client)
    require("kwargs['secure'] = True" in body and "kwargs['HTTP_HOST'] = 'cr008.example.invalid'" in body
        and 'super().post(*args, **kwargs)' in body,'Keep the retained real MFA POST and allowed production host')
    require('accounting_cr012_receipt_capacity' in forward and "DROP FUNCTION accounting_cr012_receipt_capacity(uuid,date)" in reverse,
        'Dated visible choices must share the retained temporal capacity definition')
    methods=sum(isinstance(n,ast.FunctionDef) and n.name.startswith('test_')
        for name in ('tests_demand_charges.py','tests_charge_cash.py','tests_demand_migration.py')
        for n in ast.walk(ast.parse((root/'accounting'/name).read_text())))
    require(methods==86,'Retain all86 new native financial/HTTP/migration/concurrency contracts')
    return {'local_import_symbols':imports,'local_calls_checked':required_call_arguments(root,paths),
        'new_native_contracts':methods,'expected_native_suite':1393,'retained_cr011_checks':retained,
        'application_or_tests_executed':False}
