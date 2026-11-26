"""Office-scoped, attributable notes; financial balances are never changed."""
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from .ownership import OfficeOwned

NOTE_RETAINED = 'Η σημείωση διατηρείται στο ιστορικό. Προσθέστε νέα σημείωση για συμπλήρωση ή διόρθωση.'


class CounterpartyNote(OfficeOwned):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entity = models.ForeignKey('accounting.Entity', on_delete=models.PROTECT,
        related_name='journal_notes', editable=False, verbose_name='Συναλλασσόμενος')
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        editable=False, verbose_name='Λογιστής')
    actor_label = models.CharField(max_length=150, editable=False, verbose_name='Όνομα λογιστή κατά την καταχώριση')
    request_key = models.UUIDField(editable=False)
    subject = models.CharField(max_length=200, blank=True, default='', verbose_name='Θέμα')
    body = models.TextField(max_length=5000, verbose_name='Σημείωση')
    created_at = models.DateTimeField(default=timezone.now, editable=False, verbose_name='Καταχωρίστηκε')

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError(NOTE_RETAINED)
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(NOTE_RETAINED)

    class Meta:
        ordering = ['-created_at', '-id']
        verbose_name = 'Σημείωση συναλλασσομένου'
        verbose_name_plural = 'Σημειώσεις συναλλασσομένων'
        constraints = [
            models.UniqueConstraint(fields=['office', 'request_key'], name='cr004_note_request'),
            models.CheckConstraint(condition=~models.Q(body__regex=r'^\s*$'), name='cr004_note_nonempty'),
        ]
        indexes = [models.Index(fields=['office', 'entity', '-created_at', '-id'], name='cr004_note_entity_time')]
