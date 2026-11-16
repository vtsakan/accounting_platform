"""S25 restore metadata/diagnostics only; no DB, Docker or application imports."""
import re

REHEARSAL_VERSIONS = {
    'source_server':150020, 'source_pg_dump':150020, 'source_pg_restore':150020,
    'target_server':170012, 'target_pg_dump':170012, 'target_pg_restore':170012,
}


def client_version_number(text):
    match = re.search(r'\(PostgreSQL\)\s+([0-9]+)\.([0-9]+)',text)
    if not match:
        raise ValueError('Δεν αναγνωρίζεται η πλήρης έκδοση εργαλείου PostgreSQL.')
    return int(match.group(1))*10000+int(match.group(2))


def validate_rehearsal_pair(versions):
    if set(versions) != set(REHEARSAL_VERSIONS) or any(type(versions[k]) is not int
            or versions[k] != value for k,value in REHEARSAL_VERSIONS.items()):
        raise ValueError('Το S25 χρειάζεται το δηλωμένο ζεύγος PostgreSQL 15.20/17.12 και αντίστοιχα pg_dump/pg_restore. Δεν αλλάζει υπάρχουσα βάση.')


def archive_version_numbers(text):
    values = {}
    for key,label in [('source_version_num','Dumped from database version'),('dumped_by_version_num','Dumped by pg_dump version')]:
        match = re.search(re.escape(label)+r':\s*([0-9]+)\.([0-9]+)',text)
        if not match:
            raise ValueError('Λείπει η πλήρης έκδοση πηγής ή pg_dump από το αρχείο.')
        values[key] = int(match.group(1))*10000+int(match.group(2))
    return values


def client_major(text):
    match = re.search(r'\(PostgreSQL\)\s+([0-9]+)\.', text)
    if not match:
        raise ValueError('Δεν αναγνωρίζεται η έκδοση pg_restore.')
    return int(match.group(1))


def archive_versions(text):
    result = {}
    for key, label in [('source_major', 'Dumped from database version'), ('dumped_by_major', 'Dumped by pg_dump version')]:
        match = re.search(re.escape(label) + r':\s*([0-9]+)\.', text)
        if not match:
            raise ValueError('Λείπει η έκδοση πηγής ή εργαλείου από το αρχείο ανάκτησης.')
        result[key] = int(match.group(1))
    return result


def validate_server(info, *, database, user, major):
    if (info.get('database') != database or info.get('user') != user
            or type(info.get('version')) is not int or info['version'] // 10000 != major
            or info.get('port') != 5432 or info.get('read_only') != 'off'
            or info.get('user_tables') != 0):
        raise ValueError('Η ανάκτηση χρειάζεται τον αναμενόμενο άδειο και εγγράψιμο δοκιμαστικό στόχο και ρόλο.')


def failure_category(text):
    text = text.lower()
    if re.search(r'unrecognized (?:configuration )?parameter\s+"pg_attver"',text):
        return 'postgres-attribute-version-mismatch'
    for needles, name in [
        (('unrecognized configuration parameter','unrecognized parameter'), 'unsupported-server-setting'),
        (('unsupported version',), 'unsupported-archive-version'),
        (('could not find block id', 'could not seek', 'does not support random access'), 'archive-seek-or-block'),
        (('valid archive', 'did not find magic string', 'input file is too short'), 'invalid-archive'),
        (('end of file', 'unexpected eof'), 'truncated-archive'),
        (('password authentication failed', 'no password supplied'), 'authentication'),
        (('read-only transaction',), 'read-only-target'),
        (('read-only file system', 'device or resource busy'), 'private-mount-write'),
        (('permission denied', 'must be owner'), 'permission'),
        (('already exists',), 'nonempty-target'),
        (('out of shared memory',), 'lock-budget'),
        (('no space left on device', 'disk full'), 'disk-capacity'),
        (('violates foreign key', 'violates check constraint', 'duplicate key'), 'constraint'),
        (('could not connect', 'connection refused', 'could not translate host'), 'connection'),
    ]:
        if any(needle in text for needle in needles):
            return name
    return 'unclassified'


def redact(text, secrets):
    for value in sorted({str(v) for v in secrets if v}, key=len, reverse=True):
        text = text.replace(value, '<redacted>')
    text = re.sub(r'(https?://)[^\s/@:]+:[^\s/@]+@', r'\1<redacted>@', text)
    return text


def diagnostic_parameters(text, secrets):
    # Only this known public technical identifier is disclosed; arbitrary SQL
    # identifiers, values and all other quoted strings stay redacted.
    text = redact(text,secrets)
    return ['pg_attver'] if re.search(r'unrecognized (?:configuration )?parameter\s+"pg_attver"',text,re.I) else []


def safe_error_lines(text, secrets):
    """Share error headers only, never SQL commands, COPY rows or DETAIL values."""
    result = []
    for line in redact(text, secrets).splitlines():
        if not re.match(r'^(?:pg_restore:\s*(?:error|fatal):|ERROR:|FATAL:|S25-WORKER |Error response from daemon:|Error:|docker:|sh:|cat:|chmod:|sha256sum:)', line):
            continue
        if line.startswith('S25-WORKER '):
            # The worker emits only its separately controlled safe metadata.
            result.append(line[:1000])
        else:
            line = re.sub(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"", '<quoted>', line)
            line = re.sub(r'[A-Za-z0-9_+/=!-]{24,}', '<redacted>', line)
            result.append(line[:500])
        if len(result) == 3:
            break
    return result
