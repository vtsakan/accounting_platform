"""Private attachment bytes, purpose/office/client/version bound to external keys."""
import json
import secrets

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.conf import settings
from django.core.exceptions import ValidationError
from django.views.decorators.debug import sensitive_variables


def context(office, entity, key, digest, mime):
    return json.dumps(['accounting:cr008:attachment:v1', str(office), str(entity), str(key), digest, mime],
        separators=(',', ':')).encode()


def box(secret, salt, aad):
    return AESGCM(HKDF(algorithm=hashes.SHA256(), length=32, salt=bytes(salt), info=aad).derive(secret.encode()))


@sensitive_variables('__ALL__')
def seal(office, entity, key, digest, mime, payload):
    salt=secrets.token_bytes(16);nonce=secrets.token_bytes(12)
    aad=context(office, entity, key, digest, mime)
    return salt, nonce, box(settings.SECRET_KEY,salt,aad).encrypt(nonce,payload,aad)


@sensitive_variables('__ALL__')
def unseal(row):
    aad=context(row.office_id,row.entity_id,row.pk,row.content_sha256,row.content_type)
    for secret in [settings.SECRET_KEY,*settings.SECRET_KEY_FALLBACKS]:
        try:return box(secret,row.salt,aad).decrypt(bytes(row.nonce),bytes(row.payload),aad)
        except (InvalidTag,ValueError,TypeError):continue
    raise ValidationError('Δεν ήταν δυνατή η ανάκτηση του αρχείου με το διαθέσιμο κλειδί.')
