"""Operator-only explanatory profiles in a fresh, guarded S31 synthetic project."""
import cProfile
from datetime import timedelta
import http.client
import json
from pathlib import Path
import pstats
import re
import sys
import time
from urllib.parse import urlencode

from s31_runtime_probe import client_for, fixture, guard
from r1_gate import percentile95, profile, require


def profile_requests():
    from django.conf import settings
    from django.db import connection
    from django.urls import reverse
    from django.utils import timezone
    workload = profile(json.loads(Path('/opt/s31/workload.json').read_text()))
    f = fixture(); end = timezone.localdate()
    start = end - timedelta(days=workload['synthetic_envelope']['window_days'] - 1)
    paths = {'list': reverse('transaction-list'), 'detail': reverse('entity-detail', args=[f.customer.pk]),
             'annual_report': reverse('summary-report') + '?' + urlencode({'start_date': start.isoformat(), 'end_date': end.isoformat(), 'as_of': end.isoformat()})}
    client = client_for(f.member)
    cookie = client.cookies[settings.SESSION_COOKIE_NAME].value
    sequential = {}; profiles = {}
    # These additional requests happen after the original benchmark. There is
    # no 2-second acceptance claim for a single session or an instrumented call.
    for operation, path in paths.items():
        elapsed = []
        for _ in range(10):
            began = time.perf_counter()
            transport = http.client.HTTPConnection('127.0.0.1', 8000, timeout=45)
            try:
                transport.request('GET', path, headers={'Host': 's31.example.invalid', 'X-Forwarded-Proto': 'https',
                    'Accept-Language': 'en', 'Cookie': settings.SESSION_COOKIE_NAME + '=' + cookie})
                response = transport.getresponse(); body = response.read(4 * 1024 * 1024 + 1)
                require(response.status == 200 and len(body) <= 4 * 1024 * 1024 and b'lang="el"' in body,
                        'sequential_diagnostic_HTTP_failed')
            finally:
                transport.close()
            elapsed.append(time.perf_counter() - began)
        sequential[operation] = {'samples': 10, 'p95_seconds': percentile95(elapsed), 'max_seconds': max(elapsed)}
        totals = {'executions': 0, 'elapsed_seconds': 0.0, 'by_verb': {}}
        def observe(execute, sql, params, many, context):
            began = time.perf_counter()
            try:
                return execute(sql, params, many, context)
            finally:
                # Never retain query text, parameter values, stack locals,
                # request bodies, financial rows or session material.
                verb = sql.lstrip().split(None, 1)[0].upper() if isinstance(sql, str) and sql.strip() else 'OTHER'
                if verb not in {'SELECT', 'INSERT', 'UPDATE', 'DELETE', 'SET', 'BEGIN', 'COMMIT', 'SAVEPOINT', 'RELEASE'}:
                    verb = 'OTHER'
                totals['executions'] += 1; totals['elapsed_seconds'] += time.perf_counter() - began
                totals['by_verb'][verb] = totals['by_verb'].get(verb, 0) + 1
        profiler = cProfile.Profile()
        began = time.perf_counter()
        with connection.execute_wrapper(observe):
            profiler.enable()
            try:
                response = client.get(path)
                require(response.status_code == 200 and b'lang="el"' in response.content, 'in_process_diagnostic_HTTP_failed')
            finally:
                profiler.disable()
        duration = time.perf_counter() - began
        functions = []
        for (filename, line, function), (primitive, calls, own, cumulative, callers) in pstats.Stats(profiler).stats.items():
            if not filename.startswith(('/app/accounting/', '/app/core/')) or not re.fullmatch(r'[A-Za-z0-9_.<>]+', function):
                continue
            functions.append({'source': filename.removeprefix('/app/'), 'line': line, 'function': function,
                              'calls': calls, 'own_seconds': own, 'cumulative_seconds': cumulative})
        functions.sort(key=lambda row: row['cumulative_seconds'], reverse=True)
        profiles[operation] = {'requests': 1, 'elapsed_seconds': duration, 'sql': totals, 'application_hotspots': functions[:8],
                              'scope': 'instrumented Django test client with real production settings/middleware/database; excludes Gunicorn, socket and worker queue; cumulative functions overlap'}
    return {'single_session_http_after_load': sequential, 'instrumented_in_process_after_load': profiles,
            'profiled_payloads_or_sql_saved': False, 'profiles_affect_original_450_samples': False}


if __name__ == '__main__':
    try:
        require(len(sys.argv) == 1, 'fixed_diagnostic_action_only')
        guard()
        print('S31-PERFORMANCE ' + json.dumps(profile_requests(), ensure_ascii=False, allow_nan=False))
    except Exception as error:
        # Avoid a traceback with SQL, cookies or generated configuration.
        diagnostic = {'error': type(error).__name__}
        if isinstance(error, RuntimeError) and re.fullmatch(r'[A-Za-z0-9_]{1,150}', str(error)):
            diagnostic['reason'] = str(error)
        print('S31-PERFORMANCE-PROBE-DIAG ' + json.dumps(diagnostic), file=sys.stderr)
        sys.exit(1)
