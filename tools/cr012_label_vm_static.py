"""Source/import/call/phase review only; never initialise the application or run tests."""
import ast
import builtins
from pathlib import Path
import symtable

from cr007_static_inputs import defines,target
from cr008_static_inputs import required_call_arguments
from r1_gate import require

NAMES=('preview_cr012_label_policy.py','preview_cr012_label_runtime.py',
    'preview_cr012_label_host.py','preview_cr012_label_release.py','cr012_label_transfer.py',
    'test_preview_cr012_label_vm.py','cr012_label_vm_static.py','run_cr012_label_vm_guards.py')


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
    host=(root/'tools/preview_cr012_label_host.py').read_text()
    functions={n.name:ast.unparse(n) for n in ast.parse(host).body if isinstance(n,ast.FunctionDef)}
    require('CREATE DATABASE' not in host and 'call_command' not in host and 'clone_program' not in host
        and "len(expected) == 42" in functions['stage'] and "len(state['frozen_snapshot']) == 65" in functions['prepare'],
        'Use the current42 schema and65 tables; no clone or migration entry point')
    require(functions['activate'].index("state['public_cutover_started'] = True")<functions['activate'].index("'worker', 'scheduler'")
        and 'policy.rollback_database' in functions['rollback'],
        'Persist public cutover first and keep exactly the same current database on rollback')
    require('Only the known caption insertion is allowed' in functions['stage']
        and 'Transferred native label proof differs from the immutable bundle' in functions['stage']
        and 'correction.evidence_names(policy.identity())' in functions['stage'],
        'Permit only the two known caption changes and all38 transferred native proofs')
    release_functions={n.name:ast.unparse(n) for n in ast.parse((root/'tools/preview_cr012_label_release.py').read_text()).body
        if isinstance(n,ast.FunctionDef)}
    retry=release_functions['retarget_unstarted']
    require('correction.evidence_names(policy.verify(ROOT))' in release_functions['transfer']
        and retry.index('correction.unstarted(status)')<retry.index("'plan'")
        and retry.index('correction.guarded_plan(status, plan)')<retry.index('common.private_json(CONFIG, revised)')
        and 'prior_journals_unchanged(value)' in functions['retarget_status']
        and 'STATE.exists()' in functions['retarget_status'] and 'HOLD.exists()' in functions['retarget_status']
        and 'PLAN.exists()' in functions['retarget_status'],
        'Transfer the complete closure and prove the unstarted source and corrected plan before retargeting')
    tests=root/'tools/test_preview_cr012_label_vm.py'
    new=sum(isinstance(n,ast.FunctionDef) and n.name.startswith('test_') for n in ast.walk(ast.parse(tests.read_text())))
    old=sum(isinstance(n,ast.FunctionDef) and n.name.startswith('test_')
        for path in (*sorted((root/'tools').glob('test_preview_cr008*.py')),root/'tools/test_preview_cr009_vm.py',root/'tools/test_preview_cr011_vm.py',root/'tools/test_preview_cr012_vm.py')
        for n in ast.walk(ast.parse(path.read_text())))
    require(new==33 and old==224,'Retain all249 original guards and8 new native transfer/retry contracts')
    return {'python_modules':len(files),'local_import_symbols':imports,'local_module_calls':attributes,
        'local_calls_checked':required_call_arguments(root,files),
        'original_deployment_guards':old,'new_operator_guards':new,'runtime_or_tests_executed':False}
