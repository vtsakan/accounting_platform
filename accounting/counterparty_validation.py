"""Explicit local identity syntax; no registry lookup or AFM checksum claim."""
import re
from django.core.exceptions import ValidationError

SPACES = " \t\r\n\v\f\u0085\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000"
WIDE_DIGITS = "０１２３４５６７８９"
AFM_ERROR = "Ο Α.Φ.Μ. πρέπει να αποτελείται από εννέα ψηφία ή να είναι κενός."
DUPLICATE_AFM = "Ο Α.Φ.Μ. χρησιμοποιείται ήδη σε αυτό το γραφείο, ακόμη και σε αρχειοθετημένη εγγραφή."


def afm_text(value, *, strip_prefix=True):
    text = str(value or "").translate(str.maketrans(WIDE_DIGITS, "0123456789"))
    text = text.translate(str.maketrans("", "", SPACES + "-")).upper()
    if strip_prefix and text.startswith("EL"):
        text = text[2:]
    return text


def afm_key(value):
    text = afm_text(value)
    if afm_text(value, strip_prefix=False) and not re.fullmatch(r"[0-9]{9}", text):
        raise ValidationError(AFM_ERROR, code="invalid_afm")
    return text


def contact_values(values):
    result = dict(values)
    for name in ("name", "tax_office", "address", "city", "postal_code", "phone_number", "email"):
        if name in result:
            result[name] = str(result[name] or "").strip()
    if not result.get("name"):
        raise ValidationError({"name": "Συμπληρώστε ονοματεπώνυμο ή επωνυμία."})
    for name in ("name", "tax_office", "address", "city", "postal_code", "phone_number", "email"):
        if any(ord(c) < 32 or ord(c) == 127 for c in result.get(name, "")):
            raise ValidationError({name: "Το πεδίο περιέχει μη επιτρεπόμενους χαρακτήρες."})
    phone = result.get("phone_number", "")
    if phone and (not re.fullmatch(r"\+?[0-9 ().-]+", phone) or not 7 <= len(re.sub(r"\D", "", phone)) <= 15):
        raise ValidationError({"phone_number": "Συμπληρώστε έγκυρο τηλέφωνο με 7 έως 15 ψηφία."})
    postal = result.get("postal_code", "")
    if postal and not re.fullmatch(r"[\w -]{2,10}", postal):
        raise ValidationError({"postal_code": "Ελέγξτε τον ταχυδρομικό κώδικα."})
    if "vat_number" in result:
        try:
            result["vat_number"] = afm_key(result["vat_number"])
        except ValidationError as error:
            raise ValidationError({"vat_number": error.messages}) from None
    return result
