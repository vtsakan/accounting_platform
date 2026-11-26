"""Bounded, data-only XLSX reader. No formulas, macros, external fetches or files."""
from collections import Counter
from decimal import Decimal, InvalidOperation
import io
import posixpath
import re
import unicodedata
import xml.etree.ElementTree as ET
import zipfile

MAX_BYTES = 5 * 1024 * 1024
MAX_ROWS = 250
NS = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
REL = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id'
ALIASES = {
    'ΕΠΩΝΥΜΟ': 'last_name', 'ΟΝΟΜΑ': 'first_name', 'ΕΠΩΝΥΜΙΑ': 'name',
    'ΟΝΟΜΑΤΕΠΩΝΥΜΟ': 'name', 'ΑΦΜ': 'vat_number', 'ΑΜΚΑ': 'main_amka',
    'USERNAME': 'username', 'PASSWORD': 'password',  # pragma: allowlist secret -- Excel field names, no credential values
    'TAXISNETUSERNAME': 'username', 'TAXISNETPASSWORD': 'password',  # pragma: allowlist secret -- Column identifiers, no credential values
}


class XlsxError(ValueError):
    pass


def normal_header(value):
    value = unicodedata.normalize('NFKD', value).upper()
    return ''.join(c for c in value if c.isalnum() and not unicodedata.combining(c))


def column_number(label):
    result = 0
    for c in label:
        result = result * 26 + ord(c) - 64
    return result


def column_label(number):
    result = ''
    while number:
        number, remainder = divmod(number - 1, 26)
        result = chr(65 + remainder) + result
    return result


def xml(archive, name):
    try:
        data = archive.read(name)
        if len(data) > 8 * 1024 * 1024 or b'\x00' in data or b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
            raise XlsxError('Το αρχείο περιέχει μη υποστηριζόμενη δομή.')
        return ET.fromstring(data)
    except (KeyError, ET.ParseError, UnicodeError, RuntimeError, zipfile.BadZipFile):
        raise XlsxError('Το αρχείο δεν είναι έγκυρο βιβλίο εργασίας.') from None


def identifier(value, numeric, digits):
    """Excel numeric identifiers lost their text zeros; reconstruct fixed width."""
    if numeric and value:
        try:
            number = Decimal(value)
        except InvalidOperation:
            return value, False
        if number.is_finite() and 0 <= number < 10 ** digits and number == number.to_integral_value():
            text = str(int(number)).zfill(digits)
            return text, len(str(int(number))) < digits
    return value, False


def read_workbook(payload):
    if not isinstance(payload, bytes) or not 0 < len(payload) <= MAX_BYTES:
        raise XlsxError('Επιλέξτε βιβλίο εργασίας έως 5 μεγαμπάιτ.')
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except (zipfile.BadZipFile, OSError):
        raise XlsxError('Επιλέξτε έγκυρο αρχείο .xlsx.') from None
    with archive:
        entries = archive.infolist()
        names = [x.filename for x in entries]
        if len(entries) > 512 or len(set(names)) != len(names) or sum(x.file_size for x in entries) > 32 * 1024 * 1024:
            raise XlsxError('Το βιβλίο εργασίας είναι υπερβολικά μεγάλο ή έχει διπλά τμήματα.')
        for entry in entries:
            parts = entry.filename.split('/')
            if (entry.flag_bits & 1 or entry.file_size > 8 * 1024 * 1024 or entry.filename.startswith('/')
                    or '..' in parts or '\\' in entry.filename or entry.file_size > max(1024 * 1024, entry.compress_size * 300)):
                raise XlsxError('Το αρχείο έχει μη υποστηριζόμενη συμπίεση ή προστασία.')
            if any(term in entry.filename.lower() for term in ('vbaproject', 'externallinks/', 'embeddings/', 'connections.xml', 'customxml/')):
                raise XlsxError('Χρησιμοποιήστε απλό βιβλίο δεδομένων χωρίς μακροεντολές ή εξωτερικές συνδέσεις.')
        shared = []
        if 'xl/sharedStrings.xml' in names:
            shared = [''.join(t.text or '' for t in item.iter('{'+NS['m']+'}t'))
                for item in xml(archive, 'xl/sharedStrings.xml')]
            if len(shared) > 50000 or any(len(s) > 10000 for s in shared):
                raise XlsxError('Το αρχείο περιέχει υπερβολικά μεγάλο κείμενο.')
        book = xml(archive, 'xl/workbook.xml')
        relationships = xml(archive, 'xl/_rels/workbook.xml.rels')
        if any(r.attrib.get('TargetMode') == 'External' for r in relationships):
            raise XlsxError('Δεν υποστηρίζονται εξωτερικές συνδέσεις.')
        targets = {r.attrib['Id']: r.attrib['Target'] for r in relationships}
        sheets = book.find('m:sheets', NS)
        if sheets is None or not 1 <= len(sheets) <= 10:
            raise XlsxError('Επιτρέπονται έως δέκα φύλλα δεδομένων.')
        result = []; mappings = []; cell_count = 0; characters = 0
        for sheet_index, sheet in enumerate(sheets):
            target = targets.get(sheet.attrib.get(REL), '')
            path = posixpath.normpath(target.lstrip('/') if target.startswith('/') else 'xl/' + target)
            if not path.startswith('xl/worksheets/') or not path.endswith('.xml'):
                raise XlsxError('Το φύλλο δεδομένων δεν είναι έγκυρο.')
            data = xml(archive, path).find('m:sheetData', NS)
            if data is None:
                continue
            raw = []; seen_rows = set()
            for row in data:
                if not row.tag.endswith('}row'):
                    continue
                cells = {}; number = int(row.attrib.get('r', '0'))
                if not 1 <= number <= 10000 or number in seen_rows:
                    raise XlsxError('Η αρίθμηση γραμμών δεν υποστηρίζεται.')
                seen_rows.add(number)
                for cell in row:
                    if not cell.tag.endswith('}c'):
                        continue
                    cell_count += 1
                    match = re.fullmatch(r'([A-Z]{1,3})([0-9]+)', cell.attrib.get('r', ''))
                    if cell_count > 50000 or not match or int(match[2]) != number or column_number(match[1]) > 100:
                        raise XlsxError('Επιτρέπονται έως 100 στήλες και 50.000 κελιά.')
                    if cell.find('m:f', NS) is not None:
                        raise XlsxError('Το αρχείο περιέχει τύπους. Αποθηκεύστε αντίγραφο με επικόλληση μόνο τιμών.')
                    node = cell.find('m:v', NS); value = node.text or '' if node is not None else ''
                    kind = cell.attrib.get('t', 'n')
                    if kind == 's':
                        try:
                            index = int(value)
                            if index < 0: raise ValueError()
                            value = shared[index]
                        except (ValueError, IndexError):
                            raise XlsxError('Μη έγκυρο κείμενο κελιού.') from None
                    elif kind == 'inlineStr':
                        value = ''.join(t.text or '' for t in cell.iter('{'+NS['m']+'}t'))
                    characters += len(value)
                    if characters > 2_000_000 or len(value) > 10000 or '\x00' in value or match[1] in cells:
                        raise XlsxError('Το αρχείο περιέχει μη έγκυρο ή πολύ μεγάλο κελί.')
                    if value:
                        cells[match[1]] = (value, kind == 'n')
                if cells:
                    raw.append((number, cells))
            if not raw:
                continue
            header_index = next((i for i, (_, cells) in enumerate(raw[:20])
                if 'vat_number' in {ALIASES.get(normal_header(v[0])) for v in cells.values()}
                and {'last_name', 'name'}.intersection(ALIASES.get(normal_header(v[0])) for v in cells.values())), None)
            if header_index is None:
                raise XlsxError('Κάθε φύλλο δεδομένων χρειάζεται επικεφαλίδες ΕΠΩΝΥΜΟ ή ΕΠΩΝΥΜΙΑ και ΑΦΜ.')
            header = raw[header_index][1]
            used = sorted({c for _, cells in raw[header_index:] for c in cells}, key=column_number)
            columns = [{'column': c, 'label': header[c][0] if c in header else 'Στήλη '+c+' (χωρίς τίτλο)',
                'field': ALIASES.get(normal_header(header[c][0])) if c in header else None} for c in used]
            known = [c['field'] for c in columns if c['field']]
            if any(n > 1 for n in Counter(known).values()):
                raise XlsxError('Δύο στήλες αντιστοιχούν στο ίδιο πεδίο. Διορθώστε τις επικεφαλίδες.')
            mappings.append({'sheet': sheet.attrib['name'], 'columns': columns})
            for number, cells in raw[header_index + 1:]:
                values = {}; extras = []; warnings = []
                for col in columns:
                    value, numeric = cells.get(col['column'], ('', False))
                    if col['field']:
                        if col['field'] in {'vat_number', 'main_amka'}:
                            value, padded = identifier(value.strip(), numeric, 9 if col['field'] == 'vat_number' else 11)
                            if padded:
                                warnings.append('Προστέθηκαν αρχικά μηδενικά στο '+col['label']+'. Ελέγξτε την τιμή.')
                        values[col['field']] = value
                    elif value:
                        extras.append([col['label'], value])
                result.append({'key': str(sheet_index)+':'+str(number), 'sheet': sheet.attrib['name'],
                    'row': number, 'values': values, 'extras': extras, 'warnings': warnings})
                if len(result) > MAX_ROWS:
                    raise XlsxError('Εισαγάγετε έως 250 γραμμές ανά αρχείο.')
        if not result:
            raise XlsxError('Δεν βρέθηκαν γραμμές πελατών.')
        return {'rows': result, 'mappings': mappings}
