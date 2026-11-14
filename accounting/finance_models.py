"""S18 immutable posting identities and database-written attributable audit."""
import uuid
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import models
from django.utils import timezone


class FinanceCommand(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    office=models.ForeignKey('accounting.Office',on_delete=models.PROTECT,editable=False)
    actor=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,editable=False)
    operation=models.CharField(max_length=30,choices=[('cash.post','Καταχώρηση'),('cash.transfer','Μεταφορά'),
        ('cash.reverse','Αντιλογισμός'),('cash.correct','Αντιλογισμός και αντικατάσταση'),('transfer.reverse','Αντιλογισμός μεταφοράς'),
        ('transfer.correct','Αντικατάσταση μεταφοράς'),('cash.refund','Επιστροφή χρημάτων'),('refund.reverse','Αντιλογισμός επιστροφής')])
    key_digest=models.CharField(max_length=71,editable=False)
    payload_digest=models.CharField(max_length=71,editable=False)
    state=models.CharField(max_length=12,default='pending',choices=[('pending','Σε εξέλιξη'),('completed','Ολοκληρώθηκε')])
    reason=models.CharField(max_length=500)
    created_at=models.DateTimeField(default=timezone.now,editable=False)
    completed_at=models.DateTimeField(null=True,editable=False)

    def __str__(self):
        return f'Οικονομική ενέργεια {self.pk}'

    class Meta:
        constraints=[models.UniqueConstraint(fields=['office','operation','key_digest'],name='s18_command_office_key'),
            models.UniqueConstraint(fields=['id','office'],name='s18_command_id_office'),
            models.CheckConstraint(condition=models.Q(state__in=['pending','completed']),name='s18_command_state')]
        verbose_name='Οικονομική ενέργεια'
        verbose_name_plural='Οικονομικές ενέργειες'


class FinanceAuditEvent(models.Model):
    office=models.ForeignKey('accounting.Office',on_delete=models.PROTECT,editable=False)
    actor=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True,editable=False)
    database_actor=models.CharField(max_length=128,editable=False)
    origin=models.CharField(max_length=12,choices=[('user','Χρήστης'),('database','Χειριστής βάσης'),('legacy','Αρχική απογραφή')])
    operation=models.CharField(max_length=60,editable=False)
    target_model=models.CharField(max_length=30,editable=False)
    target_id=models.PositiveBigIntegerField(editable=False)
    entry=models.OneToOneField('accounting.Transaction',on_delete=models.PROTECT,null=True,editable=False,related_name='finance_audit')
    command=models.ForeignKey(FinanceCommand,on_delete=models.PROTECT,null=True,editable=False)
    before=models.JSONField(default=dict,editable=False)
    after=models.JSONField(default=dict,editable=False)
    reason=models.CharField(max_length=500,editable=False)
    effective_date=models.DateField(null=True,editable=False)
    recorded_at=models.DateTimeField(default=timezone.now,editable=False)

    def save(self,*args,**kwargs):
        raise PermissionDenied('Το οικονομικό ιστορικό γράφεται μόνο από τους ελεγχόμενους μηχανισμούς καταχώρισης.')

    def delete(self,*args,**kwargs):
        raise PermissionDenied('Το οικονομικό ιστορικό δεν αλλάζει και δεν διαγράφεται.')

    class Meta:
        ordering=['-recorded_at','-pk']
        constraints=[models.CheckConstraint(condition=models.Q(origin__in=['user','database','legacy']),name='s18_audit_origin')]
        verbose_name='Οικονομικό ίχνος ελέγχου'
        verbose_name_plural='Οικονομικό ιστορικό ελέγχου'
