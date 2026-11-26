"""Immutable initial charge selection; cash and settlement events remain authoritative."""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from .ownership import OfficeOwned


class CashChargeSelection(OfficeOwned):
    source_cash=models.OneToOneField('accounting.Transaction',on_delete=models.PROTECT,primary_key=True,
        related_name='initial_charge_selection',editable=False)
    charge=models.ForeignKey('accounting.Charge',on_delete=models.PROTECT,editable=False)
    settlement=models.OneToOneField('accounting.SettlementCommand',on_delete=models.PROTECT,editable=False)
    actor=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,editable=False)
    allocated_amount=models.DecimalField(max_digits=12,decimal_places=2,editable=False)
    payload_sha256=models.CharField(max_length=71,editable=False)
    recorded_at=models.DateTimeField(default=timezone.now,editable=False)

    def save(self,*args,**kwargs):
        if type(self).objects.filter(pk=self.pk).exists():raise ValidationError('Η αρχική επιλογή χρέωσης διατηρείται στο ιστορικό.')
        return super().save(*args,**kwargs)

    def delete(self,*args,**kwargs):raise ValidationError('Η αρχική επιλογή χρέωσης διατηρείται στο ιστορικό.')

    class Meta:
        verbose_name='Αρχική επιλογή χρέωσης είσπραξης ή πληρωμής'
        verbose_name_plural='Αρχικές επιλογές χρεώσεων εισπράξεων και πληρωμών'
