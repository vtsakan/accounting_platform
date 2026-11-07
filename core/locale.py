"""Greek presentation and explicit Europe/Athens wall-time conversion."""

from datetime import date, datetime, timezone
from decimal import Decimal, localcontext
import re
from zoneinfo import ZoneInfo

from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

ATHENS = ZoneInfo("Europe/Athens")
CENT = Decimal("0.01")
_money = re.compile(r"(?P<sign>[+-]?)(?P<whole>(?:[0-9]+|[1-9][0-9]{0,2}(?:\.[0-9]{3})+))(?:,(?P<fraction>[0-9]{1,2}))?\Z")


def parse_euro(value):
    """Accept Greek decimal text; reject ambiguous decimal points and floats."""
    if isinstance(value, float) or isinstance(value, bool):
        raise ValidationError(_("Χρησιμοποιήστε δεκαδικό ποσό με κόμμα, π.χ. 1.234,56."), code="invalid")
    if isinstance(value, (Decimal, int)):
        result = Decimal(value)
    else:
        text = str(value).strip()
        if len(text) > 64:
            raise ValidationError(_("Το ποσό είναι υπερβολικά μεγάλο."), code="max_digits")
        match = _money.fullmatch(text)
        if not match:
            raise ValidationError(_("Χρησιμοποιήστε δεκαδικό ποσό με κόμμα, π.χ. 1.234,56."), code="invalid")
        result = Decimal(match["sign"] + match["whole"].replace(".", "") + "." + (match["fraction"] or "00"))
    if not result.is_finite():
        raise ValidationError(_("Το ποσό πρέπει να είναι πεπερασμένος αριθμός."), code="invalid")
    if len(result.as_tuple().digits) + abs(result.as_tuple().exponent) > 64:
        raise ValidationError(_("Το ποσό είναι υπερβολικά μεγάλο."), code="max_digits")
    with localcontext() as context:
        context.prec = max(28, len(result.as_tuple().digits) + abs(result.as_tuple().exponent) + 2)
        if result != result.quantize(CENT):
            raise ValidationError(_("Επιτρέπονται έως δύο δεκαδικά ψηφία."), code="max_decimal_places")
    return result


def format_euro(value, *, symbol=True):
    """Format exact Decimal/integer values; never round a business amount implicitly."""
    if value is None or value == "":
        return "—"
    if not isinstance(value, (Decimal, int)) or isinstance(value, bool):
        raise TypeError("Currency display requires Decimal or integer values.")
    value = parse_euro(value)
    number = format(value, ",.2f").translate(str.maketrans({",": ".", ".": ","}))
    return number + (" €" if symbol else "")


def greek_date(value):
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Timezone-aware datetime required.")
        value = value.astimezone(ATHENS)
    if not isinstance(value, date):
        raise TypeError("A date or aware datetime is required.")
    return value.strftime("%d/%m/%Y")


def athens_to_utc(value, *, fold=None):
    """Reject missing/ambiguous wall times unless a valid repeated-hour fold is explicit."""
    if value.tzinfo is not None:
        raise ValueError("Pass a naive local wall time; aware instants already have an offset.")
    if fold not in (None, 0, 1):
        raise ValueError("fold must be 0 or 1.")
    candidates = {}
    for candidate_fold in (0, 1):
        candidate = value.replace(tzinfo=ATHENS, fold=candidate_fold).astimezone(timezone.utc)
        back = candidate.astimezone(ATHENS)
        if back.replace(tzinfo=None) == value:
            candidates[candidate_fold] = candidate
    if not candidates:
        raise ValidationError(_("Η ώρα δεν υπάρχει λόγω αλλαγής στη θερινή ώρα. Επιλέξτε άλλη ώρα."), code="nonexistent_time")
    if len(set(candidates.values())) > 1:
        if fold is None:
            raise ValidationError(_("Η ώρα εμφανίζεται δύο φορές. Επιλέξτε την πρώτη ή τη δεύτερη εμφάνιση."), code="ambiguous_time")
        return candidates[fold]
    return next(iter(candidates.values()))


class GreekMoneyField(forms.DecimalField):
    def __init__(self, *args, **kwargs):
        kwargs["localize"] = True
        kwargs["widget"] = forms.TextInput(attrs={"class": "form-control", "inputmode": "decimal", "placeholder": "0,00"})
        super().__init__(*args, **kwargs)

    def to_python(self, value):
        if value in self.empty_values:
            return None
        return parse_euro(value)

    def prepare_value(self, value):
        return format_euro(value, symbol=False) if isinstance(value, (Decimal, int)) else value
