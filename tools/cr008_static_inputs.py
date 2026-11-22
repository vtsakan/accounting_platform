"""Static project-local import targets, route and sensitive-storage integration."""
import ast
from pathlib import Path

from cr007_static_inputs import target,defines


def function(root,path,name,seen=frozenset()):
    marker=(str(path),name)
    if marker in seen:return None
    for node in ast.parse(path.read_text()).body:
        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and node.name==name:return node
        if isinstance(node,ast.ImportFrom):
            for alias in node.names:
                if (alias.asname or alias.name)==name:
                    linked=target(root,path,node)
                    return function(root,linked,alias.name,seen|{marker}) if linked else None
    return None


def required_call_arguments(root,paths):
    """Check statically resolved fixture calls; dynamic expansions stay unknown."""
    count=0
    for path in paths:
        tree=ast.parse(path.read_text());functions={}
        for node in tree.body:
            if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):functions[node.name]=node
            if isinstance(node,ast.ImportFrom):
                linked=target(root,path,node)
                if linked:
                    for alias in node.names:
                        resolved=function(root,linked,alias.name)
                        if resolved is not None:functions[alias.asname or alias.name]=resolved
        for node in ast.walk(tree):
            if not isinstance(node,ast.Call) or not isinstance(node.func,ast.Name) or node.func.id not in functions:continue
            if any(isinstance(arg,ast.Starred) for arg in node.args) or any(kw.arg is None for kw in node.keywords):continue
            args=functions[node.func.id].args;positional=[*args.posonlyargs,*args.args]
            supplied={arg.arg for arg in positional[:len(node.args)]}|{kw.arg for kw in node.keywords}
            required={arg.arg for arg in positional[:len(positional)-len(args.defaults)]}
            required.update(arg.arg for arg,default in zip(args.kwonlyargs,args.kw_defaults) if default is None)
            missing=sorted(required-supplied)
            if missing:
                raise RuntimeError('Λείπουν υποχρεωτικά ορίσματα '+','.join(missing)+' για '+node.func.id+' στο '+str(path.relative_to(root)))
            count+=1
    return count


def inspect(root):
    root=Path(root).resolve();count=0
    paths=[*sorted((root/'accounting').glob('attachment_*.py')),root/'accounting/tests_attachments.py',
        root/'accounting/tests_attachment_support.py',root/'tools/cr008_runtime_probe.py']
    for path in paths:
        for node in ast.parse(path.read_text()).body:
            if not isinstance(node,ast.ImportFrom):continue
            linked=target(root,path,node)
            if not linked:continue
            for alias in node.names:
                if alias.name=='*' or not defines(root,linked,alias.name):
                    raise RuntimeError('Ανύπαρκτο τοπικό σύμβολο '+alias.name+' στο '+str(path.relative_to(root)))
                count+=1
    calls=required_call_arguments(root,[root/'accounting/tests_attachments.py',root/'accounting/tests_attachment_support.py'])
    return {'project_local_import_symbols':count,'explicit_fixture_calls_checked':calls,'application_or_tests_executed':False}
