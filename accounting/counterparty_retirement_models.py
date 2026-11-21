"""Retained owner deletion marker; no financial or note rows are removed."""
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from .ownership import OfficeOwned


class CounterpartyDeletion(OfficeOwned):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entity = models.OneToOneField('accounting.Entity', on_delete=models.PROTECT,
        related_name='deletion_record', editable=False)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, editable=False)
    actor_label = models.CharField(max_length=150, editable=False)
    confirmed_version = models.PositiveBigIntegerField(editable=False)
    contact_digest = models.CharField(max_length=71, editable=False)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError('Το ίχνος διαγραφής διατηρείται χωρίς αλλαγές.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Το ίχνος διαγραφής διατηρείται χωρίς αλλαγές.')

    class Meta:
        verbose_name = 'Ίχνος διαγραφής συναλλασσομένου'
        verbose_name_plural = 'Ίχνη διαγραφής συναλλασσομένων'
