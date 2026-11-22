"""Static project-local import targets, route and sensitive-storage integration."""
import ast
from pathlib import Path

from cr007_static_inputs import target,defines


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
    return {'project_local_import_symbols':count,'application_or_tests_executed':False}
