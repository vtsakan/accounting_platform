"""Static local import targets and changed visible captions, without app execution."""
import ast
from html.parser import HTMLParser
from pathlib import Path
import re


def project_module(root,parts):
    path=Path(root).joinpath(*parts)
    return path.with_suffix('.py') if path.with_suffix('.py').is_file() else path/'__init__.py' if (path/'__init__.py').is_file() else None


def target(root,path,node):
    if node.level:
        package=list(path.parent.relative_to(root).parts)
        parts=package[:len(package)-node.level+1]+(node.module or '').split('.')
    else:parts=(node.module or '').split('.')
    return project_module(root,[p for p in parts if p])


def defines(root,path,name,seen=frozenset()):
    marker=(str(path),name)
    if marker in seen:return False
    tree=ast.parse(path.read_text());seen=seen|{marker}
    for node in tree.body:
        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)) and node.name==name:return True
        if isinstance(node,(ast.Assign,ast.AnnAssign)):
            targets=node.targets if isinstance(node,ast.Assign) else [node.target]
            if any(isinstance(t,ast.Name) and t.id==name for t in targets):return True
        if isinstance(node,ast.Import):
            if any((alias.asname or alias.name.split('.')[0])==name for alias in node.names):return True
        if isinstance(node,ast.ImportFrom):
            for alias in node.names:
                if (alias.asname or alias.name)==name:
                    linked=target(root,path,node)
                    return defines(root,linked,alias.name,seen) if linked else True
    return False


class Captions(HTMLParser):
    def __init__(self):
        super().__init__();self.parts=[];self.ignored=0;self.group=False;self.options=[]
    def handle_starttag(self,tag,attrs):
        if tag in {'script','style'}:self.ignored+=1
        attrs=dict(attrs)
        if tag=='select' and attrs.get('id')=='directory-group':self.group=True
        if tag=='option' and self.group:self.options.append(attrs.get('value'))
    def handle_endtag(self,tag):
        if tag in {'script','style'}:self.ignored=max(0,self.ignored-1)
        if tag=='select':self.group=False
    def handle_data(self,value):
        if not self.ignored:self.parts.append(value)


def inspect(root):
    root=Path(root).resolve();count=0
    paths=[root/'accounting/tests_entity_profile.py',*sorted((root/'accounting').glob('entity_profile_*.py'))]
    for path in paths:
        for node in ast.parse(path.read_text()).body:
            if not isinstance(node,ast.ImportFrom):continue
            linked=target(root,path,node)
            if not linked:continue
            for alias in node.names:
                if alias.name=='*':raise RuntimeError('Απαιτούνται ρητές εισαγωγές συμβόλων: '+str(path.relative_to(root)))
                if not defines(root,linked,alias.name):
                    raise RuntimeError('Ανύπαρκτο τοπικό σύμβολο '+alias.name+' στο '+str(path.relative_to(root)))
                count+=1
    names=['counterparty_list.html','customer_list.html','supplier_list.html']
    for name in names:
        source=(root/'accounting/templates/accounting'/name).read_text()
        source=re.sub(r'(?s){%.*?%}|{{.*?}}','',source)
        parser=Captions();parser.feed(source)
        if re.search(r'[A-Za-z]{3,}',' '.join(parser.parts)):
            raise RuntimeError('Μη ελληνική στατική λεζάντα καταλόγου: '+name)
        if name=='counterparty_list.html' and parser.options!=['none','tag','kind','status']:
            raise RuntimeError('Διαφέρει η σύνταξη επιλογών ομαδοποίησης του καταλόγου.')
    return {'local_import_symbols_checked':count,'directory_template_static_captions_checked':3,
        'group_options':['none','tag','kind','status'],'application_or_tests_executed':False}
