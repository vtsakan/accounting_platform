"""S19 signed, attributable opening corrections; never operating cash transactions."""
from decimal import Decimal
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Round
from django.utils import timezone

class CashAdjustment(models.Model):
    office=models.ForeignKey('accounting.Office',on_delete=models.PROTECT,editable=False,verbose_name='Γραφείο')
    account=models.ForeignKey('accounting.CashAccount',on_delete=models.PROTECT,related_name='opening_adjustments',editable=False,verbose_name='Ταμείο')
    actor=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True,editable=False,verbose_name='Υπεύθυνος')
    amount=models.DecimalField(max_digits=12,decimal_places=2,editable=False,verbose_name='Προσαρμογή αρχικού υπολοίπου')
    effective_date=models.DateField(editable=False,verbose_name='Ημερομηνία ισχύος')
    reason=models.CharField(max_length=500,editable=False,verbose_name='Αιτιολογία')
    review_reference=models.CharField(max_length=250,editable=False,verbose_name='Αναφορά ελέγχου')
    key_digest=models.CharField(max_length=71,editable=False)
    payload_digest=models.CharField(max_length=71,editable=False)
    reversal_of=models.OneToOneField('self',on_delete=models.PROTECT,null=True,editable=False,related_name='reversal',verbose_name='Αρχική προσαρμογή')
    recorded_at=models.DateTimeField(default=timezone.now,editable=False,verbose_name='Καταγράφηκε')

    def save(self,*args,**kwargs):
        from .finance_money import money
        self.amount=money(self.amount,signed=True)
        if not self.amount:raise ValidationError('Η προσαρμογή πρέπει να διαφέρει από το μηδέν.')
        if self.pk:raise ValidationError('Η προσαρμογή δεν αλλάζει. Καταχωρίστε συνδεδεμένο αντιλογισμό.')
        return super().save(*args,**kwargs)

    def delete(self,*args,**kwargs):
        raise ValidationError('Οι προσαρμογές και το ιστορικό τους δεν διαγράφονται.')

    class Meta:
        ordering=['-effective_date','-pk']
        constraints=[models.UniqueConstraint(fields=['id','office'],name='s19_adjust_id_office'),
            models.UniqueConstraint(fields=['office','key_digest'],name='s19_adjust_key'),
            models.CheckConstraint(condition=models.Q(amount__gte=Decimal('-9999999999.99'),amount__lte=Decimal('9999999999.99'),amount=Round('amount',2)) & ~models.Q(amount=0),name='s19_adjust_signed_cents')]
        indexes=[models.Index(fields=['office','account','effective_date'],name='s19_adjust_date_idx')]
        verbose_name='Προσαρμογή αρχικού υπολοίπου'
        verbose_name_plural='Προσαρμογές αρχικού υπολοίπου'

class FinanceStructureLock(models.Model):
    """Writable office guard makes raw-SQL hierarchy changes safe under RR too."""
    office=models.OneToOneField('accounting.Office',on_delete=models.CASCADE,primary_key=True,related_name='finance_structure_lock')
    revision=models.BigIntegerField(default=0)
