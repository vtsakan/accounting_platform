"""Purpose-separated, identity-bound encryption under external signing material."""
import base64
import json
import secrets

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.conf import settings
from django.core.exceptions import ValidationError
from django.views.decorators.debug import sensitive_variables


@sensitive_variables('__ALL__')
def cipher(office_id, entity_id, subject, salt):
    context = json.dumps(['accounting:cr007:taxisnet:v1', str(office_id), str(entity_id), subject], separators=(',', ':')).encode()
    return MultiFernet([Fernet(base64.urlsafe_b64encode(HKDF(algorithm=hashes.SHA256(), length=32,
        salt=bytes(salt), info=context).derive(key.encode()))) for key in [settings.SECRET_KEY, *settings.SECRET_KEY_FALLBACKS]])


@sensitive_variables('__ALL__')
def seal(office_id, entity_id, subject, username, password):
    salt = secrets.token_bytes(16)
    box = cipher(office_id, entity_id, subject, salt)
    return salt, box.encrypt(username.encode()), box.encrypt(password.encode())


@sensitive_variables('__ALL__')
def open_sealed(record):
    try:
        box = cipher(record.office_id, record.entity_id, record.subject, record.salt)
        return box.decrypt(bytes(record.sealed_username)).decode(), box.decrypt(bytes(record.sealed_password)).decode()
    except (InvalidToken, UnicodeError, ValueError):
        raise ValidationError('Δεν ήταν δυνατή η ανάκτηση των κωδικών με το διαθέσιμο κλειδί.') from None
