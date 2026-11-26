"""Excel preview encryption, separated from credentials, MFA and attachment keys."""
import base64
import json
import secrets

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.conf import settings
from django.core.exceptions import ValidationError
from django.views.decorators.debug import sensitive_variables


def cipher(row):
    info = json.dumps(['accounting:cr010:excel-preview:v1', str(row.office_id), str(row.actor_id),
        str(row.pk), row.source_sha256], separators=(',', ':')).encode()
    return MultiFernet([Fernet(base64.urlsafe_b64encode(HKDF(algorithm=hashes.SHA256(), length=32,
        salt=bytes(row.salt), info=info).derive(key.encode()))) for key in [settings.SECRET_KEY, *settings.SECRET_KEY_FALLBACKS]])


@sensitive_variables('__ALL__')
def seal(row, value):
    row.salt = secrets.token_bytes(16)
    row.payload = cipher(row).encrypt(json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode())


@sensitive_variables('__ALL__')
def open_preview(row):
    try:
        return json.loads(cipher(row).decrypt(bytes(row.payload)).decode())
    except (InvalidToken, UnicodeError, ValueError, TypeError):
        raise ValidationError('Η προεπισκόπηση δεν ανακτάται. Ανεβάστε ξανά το αρχείο.') from None
