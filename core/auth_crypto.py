"""Authenticated encryption for MFA seeds; signing keys stay outside the DB."""
import base64
import secrets

from cryptography.fernet import Fernet, MultiFernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.conf import settings


def new_salt():
    return secrets.token_bytes(16)


def cipher(user_id, salt):
    info = b"accounting:s13:mfa:v1:" + str(user_id).encode("ascii")
    keys = [settings.SECRET_KEY, *settings.SECRET_KEY_FALLBACKS]
    return MultiFernet([Fernet(base64.urlsafe_b64encode(HKDF(
        algorithm=hashes.SHA256(), length=32, salt=bytes(salt), info=info
    ).derive(key.encode("utf-8")))) for key in keys])
