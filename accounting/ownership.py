"""Office-bound model validation; PostgreSQL also enforces linked ownership."""
from django.core.exceptions import ValidationError
from django.db import models


class OfficeOwned(models.Model):
    office = models.ForeignKey("accounting.Office", on_delete=models.PROTECT,
                              editable=False, verbose_name="Λογιστικό γραφείο")
    office_unique_fields = ()

    class Meta:
        abstract = True

    def validate_ownership(self):
        if not self.office_id:
            raise ValidationError("Απαιτείται λογιστικό γραφείο για την εγγραφή.")
        if self.pk:
            previous = type(self).objects.filter(pk=self.pk).values_list("office_id", flat=True)
            if previous.exists() and str(previous.first()) != str(self.office_id):
                raise ValidationError("Δεν επιτρέπεται η αλλαγή γραφείου της εγγραφής.")
        for field in self._meta.concrete_fields:
            related = field.remote_field.model if field.is_relation else None
            if related is not None and isinstance(related, type) and issubclass(related, OfficeOwned):
                key = getattr(self, field.attname)
                if key is not None and not related.objects.filter(pk=key, office_id=self.office_id).exists():
                    raise ValidationError("Οι συνδεδεμένες εγγραφές πρέπει να ανήκουν στο ίδιο λογιστικό γραφείο.")
        for field in self.office_unique_fields:
            value = getattr(self, field)
            if value not in (None, "") and type(self).objects.filter(
                    office_id=self.office_id, **{field: value}).exclude(pk=self.pk).exists():
                raise ValidationError({field: "Η τιμή χρησιμοποιείται ήδη σε αυτό το λογιστικό γραφείο."})

    def clean(self):
        super().clean()
        self.validate_ownership()

    def save(self, *args, **kwargs):
        self.validate_ownership()
        return super().save(*args, **kwargs)
