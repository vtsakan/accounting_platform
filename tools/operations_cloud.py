"""Selected-project Monitoring and prefix-scoped backup lifecycle, operator auth."""

import json
import re
from datetime import datetime, timedelta, timezone
import urllib.parse

from cloud import account, require
import operations_common as common
import preview as laptop


def project(config):
    return config['preview']['gcp']['project_id']


def metric_filter(config, name):
    return ('resource.type="gce_instance" AND resource.label.instance_id="' + config['instance_id']
            + '" AND metric.type="' + common.METRIC_PREFIX + name + '"')


def lifecycle(config):
    return {'rule': [{'action': {'type': 'Delete'}, 'condition': {
        'age': config['retention_days'], 'matchesPrefix': [common.PREFIX], 'isLive': True}}]}


def uptime(config):
    return {'displayName': 'Λογιστική — διαθεσιμότητα προεπισκόπησης', 'period': '300s', 'timeout': '10s',
            'monitoredResource': {'type': 'uptime_url', 'labels': {'project_id': project(config), 'host': config['preview']['hostname']}},
            'httpCheck': {'path': '/health/ready/', 'port': 443, 'useSsl': True, 'validateSsl': True, 'requestMethod': 'GET',
                          'acceptedResponseStatusCodes': [{'statusValue': 200}]},
            'contentMatchers': [{'content': '"ready"', 'matcher': 'CONTAINS_STRING'}],
            'userLabels': {'application': 'accounting-preview', 'step': 's10'}}


def descriptors():
    return [{'type': common.METRIC_PREFIX + name, 'metricKind': 'GAUGE', 'valueType': 'DOUBLE',
             'displayName': 'Accounting preview / ' + name, 'unit': 's' if name.endswith('_seconds') else '1',
             'description': 'Synthetic preview operational measurement; contains no client data.'}
            for name in common.METRIC_NAMES]


def descriptor_resource(metric_type):
    # Monitoring discovery defines this route as v3/{+name}. The reserved
    # expansion preserves slash separators in the metric resource name.
    require(metric_type in {common.METRIC_PREFIX + name for name in common.METRIC_NAMES}, 'Unexpected S10 metric type')
    return 'metricDescriptors/' + metric_type


def policies(config, channel, check):
    result = []

    def policy(key, title, condition):
        result.append({'displayName': 'Λογιστική — ' + title, 'enabled': True, 'combiner': 'OR',
            'notificationChannels': [channel], 'conditions': [{'displayName': title, **condition}],
            'userLabels': {'application': 'accounting-preview', 'step': 's10', 'check': key},
            'documentation': {'mimeType': 'text/markdown',
                'content': 'Ελέγξτε την προεπισκόπηση totalaccounting και το εγχειρίδιο λειτουργίας S10. '
                           'Μην καταχωρίζετε κωδικούς ή στοιχεία πελατών στις σημειώσεις συμβάντος.'},
            'alertStrategy': {'autoClose': '3600s'}})

    def threshold(key, title, name, comparison, value, duration='300s'):
        policy(key, title, {'conditionThreshold': {'filter': metric_filter(config, name), 'comparison': comparison,
            'thresholdValue': value, 'duration': duration, 'trigger': {'count': 1},
            'aggregations': [{'alignmentPeriod': '300s', 'perSeriesAligner': 'ALIGN_MEAN'}]}})

    threshold('backup-age', 'καθυστερημένο ή ελλιπές αντίγραφο', 'backup_age_seconds', 'COMPARISON_GT', 72000)
    threshold('backup-failed', 'αποτυχία αντιγράφου', 'backup_last_attempt_ok', 'COMPARISON_LT', 0.5)
    threshold('disk', 'χρήση δίσκου άνω του 80%', 'disk_used_ratio', 'COMPARISON_GT', 0.80)
    threshold('memory', 'χρήση μνήμης άνω του 85%', 'memory_used_ratio', 'COMPARISON_GT', 0.85, '900s')
    threshold('certificate', 'λήξη πιστοποιητικού σε λιγότερες από 14 ημέρες', 'certificate_seconds', 'COMPARISON_LT', 14 * 86400)
    threshold('readiness', 'η εφαρμογή δεν είναι έτοιμη', 'readiness', 'COMPARISON_LT', 0.5)
    threshold('alert-test', 'δοκιμή ειδοποίησης S10', 'alert_probe', 'COMPARISON_GT', 0.5, '0s')
    policy('heartbeat', 'απουσία μετρήσεων επί 15 λεπτά', {'conditionAbsent': {
        'filter': metric_filter(config, 'heartbeat'), 'duration': '900s', 'trigger': {'count': 1},
        'aggregations': [{'alignmentPeriod': '300s', 'perSeriesAligner': 'ALIGN_MEAN'}]}})
    check_id = check.rsplit('/', 1)[-1]
    policy('public-https', 'αποτυχία δημόσιου HTTPS', {'conditionThreshold': {
        'filter': 'metric.type="monitoring.googleapis.com/uptime_check/check_passed" AND metric.label.check_id="' + check_id + '" AND resource.type="uptime_url"',
        'comparison': 'COMPARISON_GT', 'thresholdValue': 1, 'duration': '300s', 'trigger': {'count': 1},
        'aggregations': [{'alignmentPeriod': '300s', 'perSeriesAligner': 'ALIGN_NEXT_OLDER',
                          'crossSeriesReducer': 'REDUCE_COUNT_FALSE', 'groupByFields': ['resource.label.host']}]}})
    return result


def subset(actual, expected):
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(k in actual and subset(actual[k], v) for k, v in expected.items())
    if isinstance(expected, list):
        return isinstance(actual, list) and len(actual) == len(expected) and all(subset(a, b) for a, b in zip(actual, expected))
    return actual == expected


class Client:
    def __init__(self, config):
        self.config = config
        self.token = laptop.gcloud(config['preview'], 'auth', 'print-access-token').decode().strip()
        require(self.token and '\n' not in self.token, 'Unexpected operator token response')
        self.base = 'https://monitoring.googleapis.com/v3/projects/' + project(config)

    def call(self, method, suffix, body=None):
        return common.api(method, self.base + '/' + suffix, self.token, body)

    def listing(self, collection, parameters=None):
        rows, page = [], ''
        for _ in range(100):
            query = dict(parameters or {})
            if page:
                query['pageToken'] = page
            data = self.call('GET', collection + ('?' + urllib.parse.urlencode(query) if query else ''))
            rows.extend(data.get(collection, []))
            page = data.get('nextPageToken')
            if not page:
                return rows
        raise RuntimeError('Monitoring listing exceeded pagination budget')

    def ensure(self, collection, desired):
        matches = [row for row in self.listing(collection) if row.get('displayName') == desired['displayName']]
        require(len(matches) <= 1, 'Duplicate S10 Monitoring display name; inspect without deleting resources')
        if matches:
            require(subset(matches[0], desired), 'Existing S10 Monitoring configuration differs; review it before changing')
            return matches[0]
        return self.call('POST', collection, desired)


def apply(config):
    p = config['preview']
    # Only this limited project role is added. Bucket create-only IAM is retained.
    laptop.gcloud(p, 'services', 'enable', 'monitoring.googleapis.com')
    laptop.gcloud(p, 'projects', 'add-iam-policy-binding', project(config),
                  '--member=serviceAccount:' + account(p['gcp']), '--role=roles/monitoring.metricWriter', '--condition=None')
    client = Client(config)
    bucket_url = 'https://storage.googleapis.com/storage/v1/b/' + config['bucket']
    bucket = common.api('GET', bucket_url, client.token)
    require(bucket['location'].upper() == p['gcp']['region'].upper()
            and bucket.get('iamConfiguration', {}).get('uniformBucketLevelAccess', {}).get('enabled') is True
            and bucket.get('iamConfiguration', {}).get('publicAccessPrevention') == 'enforced'
            and not bucket.get('versioning', {}).get('enabled'), 'Private EU backup bucket policy differs')
    expected = lifecycle(config)
    if bucket.get('lifecycle', {}).get('rule'):
        require(bucket['lifecycle'] == expected, 'Existing bucket lifecycle differs; no unrelated retention was overwritten')
    else:
        common.api('PATCH', bucket_url + '?ifMetagenerationMatch=' + bucket['metageneration'], client.token, {'lifecycle': expected})
    channel = client.ensure('notificationChannels', {'displayName': 'Λογιστική — ειδοποιήσεις προεπισκόπησης',
         'type': 'email', 'labels': {'email_address': config['alert_email']}, 'enabled': True,
         'userLabels': {'application': 'accounting-preview', 'step': 's10'}})
    for descriptor in descriptors():
        suffix = descriptor_resource(descriptor['type'])
        try:
            existing = client.call('GET', suffix)
        except common.APIError as error:
            if error.status != 404:
                raise
            existing = client.call('POST', 'metricDescriptors', descriptor)
        require(subset(existing, {k: descriptor[k] for k in ('type', 'metricKind', 'valueType', 'unit')}), 'Existing metric schema differs')
    check = client.ensure('uptimeCheckConfigs', uptime(config))
    alerts = [client.ensure('alertPolicies', policy)['name'] for policy in policies(config, channel['name'], check['name'])]
    return {'channel': channel['name'], 'uptime': check['name'], 'policies': alerts,
            'notification_status': channel.get('verificationStatus', 'VERIFICATION_STATUS_UNSPECIFIED'),
            'lifecycle_days': config['retention_days'], 'applied_at': common.now()}


def summary(config):
    """Read partial setup without creating resources or exposing contact labels."""
    client = Client(config)
    bucket = common.api('GET', 'https://storage.googleapis.com/storage/v1/b/' + config['bucket'], client.token)
    channels = client.listing('notificationChannels')
    metrics = client.listing('metricDescriptors', {'filter': 'metric.type = starts_with("' + common.METRIC_PREFIX + '")'})
    checks = client.listing('uptimeCheckConfigs')
    alerts = client.listing('alertPolicies')
    owned = lambda rows: [r for r in rows if r.get('userLabels', {}).get('application') == 'accounting-preview'
                          and r.get('userLabels', {}).get('step') == 's10']
    metric_names = {r.get('type', '').removeprefix(common.METRIC_PREFIX) for r in metrics}
    policy_names = {r.get('userLabels', {}).get('check') for r in owned(alerts)}
    policy_keys = {r['userLabels']['check'] for r in policies(config, 'channel', 'check')}
    return {'status': 'Inspected', 'retention_days': config['retention_days'],
            'lifecycle_matches_selected_policy': bucket.get('lifecycle') == lifecycle(config),
            'notification_channels': len(owned(channels)),
            'metric_descriptors': sorted(metric_names.intersection(common.METRIC_NAMES)),
            'uptime_checks': len(owned(checks)), 'alert_policies': sorted(policy_names.intersection(policy_keys)),
            'cloud_changed': False, 'private_config_changed': False}


def inspect(config):
    require(config.get('cloud'), 'Apply the selected Monitoring/lifecycle configuration first')
    client, receipt = Client(config), config['cloud']
    bucket_url = 'https://storage.googleapis.com/storage/v1/b/' + config['bucket']
    bucket = common.api('GET', bucket_url, client.token)
    require(bucket.get('lifecycle') == lifecycle(config), 'Backup lifecycle is missing or differs')
    require(bucket.get('iamConfiguration', {}).get('publicAccessPrevention') == 'enforced'
            and bucket.get('iamConfiguration', {}).get('uniformBucketLevelAccess', {}).get('enabled') is True, 'Backup bucket privacy differs')
    iam = common.api('GET', bucket_url + '/iam', client.token)
    member = 'serviceAccount:' + account(config['preview']['gcp'])
    vm_roles = [b for b in iam.get('bindings', []) if member in b.get('members', [])]
    require(len(vm_roles) == 1 and vm_roles[0]['role'] == 'roles/storage.objectCreator' and not vm_roles[0].get('condition'), 'VM backup bucket authority differs from create-only')
    channel = client.call('GET', receipt['channel'].split('/', 2)[-1])
    require(channel.get('enabled') and channel.get('type') == 'email'
            and channel.get('verificationStatus') != 'UNVERIFIED', 'Notification channel requires verification')
    check = client.call('GET', receipt['uptime'].split('/', 2)[-1])
    require(subset(check, uptime(config)) and not check.get('disabled', False), 'Public uptime check differs or is disabled')
    expected = policies(config, receipt['channel'], receipt['uptime'])
    require(len(receipt['policies']) == len(expected), 'Missing alert policies')
    for name, policy in zip(receipt['policies'], expected):
        actual = client.call('GET', name.split('/', 2)[-1])
        require(subset(actual, policy), 'Alert policy differs from the reviewed configuration')
    return {'private_bucket': True, 'create_only_vm_bucket_binding': True, 'retention_days': config['retention_days'],
            'policies': len(expected), 'external_https_check': True, 'notification_channel_enabled': True,
            'channel_verification': channel.get('verificationStatus', 'VERIFICATION_STATUS_UNSPECIFIED')}


def observed(config):
    client = Client(config)
    end = datetime.now(timezone.utc)
    interval = {'interval.startTime': (end - timedelta(minutes=20)).isoformat(), 'interval.endTime': end.isoformat(), 'view': 'FULL'}
    def points(filter_value):
        query = urllib.parse.urlencode({**interval, 'filter': filter_value})
        series = client.call('GET', 'timeSeries?' + query).get('timeSeries', [])
        return [point for row in series for point in row.get('points', [])]
    heartbeat = points(metric_filter(config, 'heartbeat'))
    probe = points(metric_filter(config, 'alert_probe'))
    check_id = config['cloud']['uptime'].rsplit('/', 1)[-1]
    public = points('resource.type="uptime_url" AND metric.type="monitoring.googleapis.com/uptime_check/check_passed" AND metric.label.check_id="' + check_id + '"')
    require(any(p['value'].get('doubleValue') == 1 for p in heartbeat), 'Cloud Monitoring has not ingested a heartbeat; retry after ingestion')
    require(any(p['value'].get('doubleValue') == 1 for p in probe), 'Run the explicit alert-test and allow Monitoring ingestion')
    require(any(p['value'].get('boolValue') is True for p in public), 'Public uptime check has not reported a passing sample yet')
    return {'recent_heartbeat_observed': True, 'recent_alert_probe_observed': True, 'public_uptime_sample_passed': True}


def latest_receipt(config):
    # Operator auth only: works with the source VM stopped or destroyed.
    client = Client(config)
    base = 'https://storage.googleapis.com/storage/v1/b/' + config['bucket'] + '/o'
    rows, page = [], ''
    for _ in range(100):
        query = urllib.parse.urlencode({'prefix': common.PREFIX, 'fields': 'items(name,generation),nextPageToken', 'pageToken': page})
        data = common.api('GET', base + '?' + query, client.token)
        rows.extend(item for item in data.get('items', []) if re.fullmatch(re.escape(common.PREFIX) + r'[0-9]{8}T[0-9]{6}Z-[0-9a-f]{32}\.receipt\.json', item['name']))
        page = data.get('nextPageToken', '')
        if not page:
            break
    else:
        raise RuntimeError('Backup receipt listing exceeded its budget')
    require(rows, 'No complete backup receipt exists in private storage yet')
    selected = max(rows, key=lambda row: row['name'])
    query = urllib.parse.urlencode({'alt': 'media', 'generation': selected['generation']})
    receipt = common.api('GET', base + '/' + urllib.parse.quote(selected['name'], safe='') + '?' + query, client.token)
    common.validate_receipt(receipt, config, max_age=None)
    require(receipt['object'].removesuffix('.tar.age') + '.receipt.json' == selected['name'], 'Recovery receipt points to another object')
    return receipt
