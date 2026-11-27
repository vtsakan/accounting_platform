"""Source/import/call/phase review only; never initialise the application or run tests."""
import ast
import builtins
from pathlib import Path
import symtable

from cr007_static_inputs import defines,target
from cr008_static_inputs import required_call_arguments
from r1_gate import require

NAMES=('preview_cr012_policy.py','preview_cr012_runtime.py','preview_cr012_migrate.py',
    'preview_cr012_host.py','preview_cr012_release.py','test_preview_cr012_vm.py','cr012_vm_static.py','run_cr012_vm_guards.py')


def inspect(root):
    root=Path(root).resolve();files=[root/'tools'/name for name in NAMES];imports=0;attributes=0
    for path in files:
        text=path.read_text();tree=ast.parse(text)
        table=symtable.symtable(text,str(path),'exec')
        known=set(table.get_identifiers())|set(dir(builtins))|{'__name__','__file__','__package__'}
        def check(scope):
            for symbol in scope.get_symbols():
                require(not(symbol.is_global() and symbol.is_referenced() and symbol.get_name() not in known),
                    'Unknown deployment global: '+path.name+':'+symbol.get_name())
            for child in scope.get_children():check(child)
        check(table)
        modules={}
        for node in tree.body:
            if isinstance(node,ast.Import):
                for alias in node.names:
                    linked=root/'tools'/(alias.name.replace('.','/')+'.py')
                    if linked.is_file():modules[alias.asname or alias.name]=linked
            if not isinstance(node,ast.ImportFrom):continue
            linked=target(root,path,node)
            if linked is None and node.level==0:
                candidate=root/'tools'/((node.module or '').replace('.','/')+'.py')
                if candidate.is_file():linked=candidate
            if linked:
                for alias in node.names:
                    require(alias.name!='*' and defines(root,linked,alias.name),
                        'Unknown deployment import: '+path.name+':'+alias.name)
                    imports+=1
        for node in ast.walk(tree):
            if not isinstance(node,ast.Call) or not isinstance(node.func,ast.Attribute) or not isinstance(node.func.value,ast.Name):continue
            linked=modules.get(node.func.value.id)
            if linked is not None:
                require(defines(root,linked,node.func.attr),'Unknown deployment API: '+path.name+':'+ast.unparse(node.func))
                attributes+=1
    host=(root/'tools/preview_cr012_host.py').read_text()
    functions={n.name:ast.unparse(n) for n in ast.parse(host).body if isinstance(n,ast.FunctionDef)}
    activation=functions['activate'];abort=functions['abort']
    require(activation.index("state['public_cutover_started'] = True")<activation.index("'worker', 'scheduler'")
        and 'abort(' not in activation and 'rollback(' not in activation
        and abort.index('policy.before_public(state)')<abort.index('runtime.bind('),
        'Persist cutover before writers and reject old-database rollback afterwards')
    require('WITH TEMPLATE' in functions['prepare'] and "clone_program(state, 'migrate')" in functions['prepare']
        and '40' in (root/'tools/preview_cr012_migrate.py').read_text()
        and (root/'compose.preview-cr008-memory.yml').read_text().count('192m')==1,
        'Keep the explicit clone and proven scheduler memory overlay')
    migration=(root/'tools/preview_cr012_migrate.py').read_text()
    require("len(applied) == 40 and applied[-1] == '0040_staff_access_guards'" in migration
        and "len(applied) == 42 and applied[-1] == '0042_demand_charge_guards'" in migration
        and "len(original)==64" in migration
        and "new_tables == ['accounting_cashchargeselection']" in migration
        and 'snapshot(original)' in migration,
        'Require exact CURRENT40/64 tables and42/65 target with one empty table and preserved rows')
    require("for name in (policy.BASELINE, policy.RECEIPT)" in ast.unparse(ast.parse(host))
        and "len(state['frozen_snapshot']) == 64" in functions['prepare']
        and "len(state['candidate_snapshot']) == 65" in functions['prepare']
        and 'The transferred host tool differs from the immutable bundle' in functions['stage'],
        'Keep the transferred native binding and frozen64/65-table snapshots')
    tests=root/'tools/test_preview_cr012_vm.py'
    new=sum(isinstance(n,ast.FunctionDef) and n.name.startswith('test_') for n in ast.walk(ast.parse(tests.read_text())))
    old=sum(isinstance(n,ast.FunctionDef) and n.name.startswith('test_')
        for path in (*sorted((root/'tools').glob('test_preview_cr008*.py')),root/'tools/test_preview_cr009_vm.py',root/'tools/test_preview_cr011_vm.py')
        for n in ast.walk(ast.parse(path.read_text())))
    require(new==48 and old==176,'Retain all176 original guards and48 new native deployment contracts')
    return {'python_modules':len(files),'local_import_symbols':imports,'local_module_calls':attributes,
        'local_calls_checked':required_call_arguments(root,files),
        'original_deployment_guards':old,'new_operator_guards':new,'runtime_or_tests_executed':False}
