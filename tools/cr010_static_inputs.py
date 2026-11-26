"""AST/route/source review only; no application or test execution."""
import ast
import json
from pathlib import Path

from cr007_static_inputs import defines, target
from cr008_static_inputs import required_call_arguments
from cr009_static_inputs import inspect as retained_inspect
from r1_gate import require


def inspect(root):
    root = Path(root).resolve(); retained = retained_inspect(root)
    files = ['accounting/cr010_models.py', 'accounting/manual_agreement_creation.py',
        'accounting/client_import_services.py', 'accounting/client_import_views.py',
        'accounting/tests_cr010_import.py', 'accounting/tests_cr010_workflow.py',
        'core/client_xlsx.py', 'core/import_crypto.py', 'accounting/tests_cr010_historical_notes.py']
    imports = 0
    for name in files:
        path = root/name
        for node in ast.parse(path.read_text()).body:
            if not isinstance(node, ast.ImportFrom): continue
            linked = target(root, path, node)
            if not linked: continue
            for alias in node.names:
                require(alias.name != '*' and defines(root, linked, alias.name), 'Unknown CR010 import: '+name+':'+alias.name)
                imports += 1
    forms = (root/'accounting/agreement_creation_forms.py').read_text()
    require('create_manual(' in forms and 'create_with_charge' not in forms
        and 'first_charge_amount =' not in forms and 'due_date =' not in forms,
        'New agreement forms must save terms without posting an initial charge')
    manual = (root/'accounting/manual_agreement_creation.py').read_text()
    require('post_charge' not in manual and 'save_terms(' in manual and 'AgreementCreationReceipt' in manual,
        'Terms-only retries need their own durable receipt')
    services = (root/'accounting/client_import_services.py').read_text()
    require('scan_content(payload)' in services and 'seal(row,' in services and '@transaction.atomic' in services
        and 'row_snapshot(entity)' in services and 'row.payload = b' in services and 'post_cash' not in services,
        'Excel requires real scanning, encrypted previews, stale checks and atomic confirmation')
    parser = (root/'core/client_xlsx.py').read_text()
    require('MAX_ROWS = 250' in parser and 'MAX_BYTES = 5 * 1024 * 1024' in parser
        and 'urlopen' not in parser and 'extractall' not in parser and 'eval(' not in parser,
        'Keep bounded, data-only Excel parsing')
    matrix = json.loads((root/'accounting/office_boundary_matrix.json').read_text())
    routes = {r['route']: r for r in matrix['routes']}
    for name, methods in {'task-pending': ['POST'], 'task-resume': ['POST'], 'counterparty-import': ['GET', 'POST'],
            'counterparty-import-preview': ['GET'], 'counterparty-import-confirm': ['POST'], 'counterparty-import-cancel': ['POST']}.items():
        require(routes[name]['methods'] == methods and routes[name]['realm'] == 'office-business', 'Declare new route: '+name)
    legacy_classes = {'accounting/tests_counterparty_journal.py': 'NoteMigrationTests',
        'accounting/tests_counterparty_retirement.py': 'RetirementMigrationContracts',
        'accounting/tests_client_tasks.py': 'TaskMigrationContracts'}
    for name, selected in legacy_classes.items():
        classes = [node for node in ast.parse((root/name).read_text()).body if isinstance(node, ast.ClassDef)]
        actual = [node.name for node in classes if any(isinstance(base, ast.Name)
            and base.id == 'HistoricalNoteMigrationSupport' for base in node.bases)]
        require(actual == [selected], 'Historical note fixtures must be limited to the selected migration class: '+name)
    helper = (root/'accounting/tests_cr010_historical_notes.py').read_text()
    require('project_state(NOTE_TARGET).apps' in helper and "'0028_counterparty_note_guards'" in helper
        and 'columns != expected_columns' in helper and 'cls.enterClassContext(' in helper
        and 'note.refresh_from_db()' in helper and 'DISABLE TRIGGER' not in helper
        and 'MigrationExecutor(connection).migrate' not in helper,
        'Historical fixtures must use the exact old model and retain real guards and migration targets')
    for path in (root/'accounting').glob('*.py'):
        if not path.name.startswith('tests'):
            require('tests_cr010_historical_notes' not in path.read_text(), 'Business code cannot import a historical test fixture')
    return {'local_import_symbols': imports, 'local_calls_checked': required_call_arguments(root, [root/n for n in files]),
        'historical_note_fixture_classes_checked': len(legacy_classes),
        'retained_gsis_attachment_checks': retained, 'application_or_tests_executed': False}
