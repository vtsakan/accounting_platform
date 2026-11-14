"""Reviewed D08 cents contract. Display parsing stays in core.locale."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
from django.core.exceptions import ValidationError

CENT=Decimal('0.01')
MAX=Decimal('9999999999.99')
INVALID='Το ποσό πρέπει να είναι θετικό, πεπερασμένο και να έχει έως δύο δεκαδικά ψηφία.'
IMMUTABLE='Η καταχωρισμένη κίνηση δεν αλλάζει και δεν διαγράφεται. Χρησιμοποιήστε συνδεδεμένο αντιλογισμό.'


def money(value, *, signed=False):
    if isinstance(value,(bool,float)) or not isinstance(value,(str,int,Decimal)):
        raise ValidationError(INVALID)
    try:
        if isinstance(value,str) and (len(value)>40 or any(c not in '-0123456789.' for c in value)):
            raise InvalidOperation
        result=Decimal(value)
        if not result.is_finite() or abs(result)>MAX or result.as_tuple().exponent < -2 or (not signed and result<=0):
            raise InvalidOperation
        return result.quantize(CENT)
    except (InvalidOperation,ValueError,TypeError):raise ValidationError(INVALID) from None


def rounded_line(unit_price,quantity):
    if isinstance(unit_price,(float,bool)) or isinstance(quantity,(float,bool)):
        raise ValidationError(INVALID)
    try:
        with localcontext() as context:
            context.prec=48
            price,count=Decimal(unit_price),Decimal(quantity)
            if not price.is_finite() or not count.is_finite() or price<=0 or count<=0 or len(str(price))+len(str(count))>80:
                raise InvalidOperation
            return money((price*count).quantize(CENT,rounding=ROUND_HALF_UP))
    except (InvalidOperation,ValueError,TypeError):raise ValidationError(INVALID) from None
