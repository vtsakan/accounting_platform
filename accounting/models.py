# accounting/models.py

from django.db import models
import uuid
from django.db.models import Sum
from django.db.models.functions import Coalesce, Round
from decimal import Decimal
from django.conf import settings
from django.core.validators import RegexValidator
from .ownership import OfficeOwned


# ===================================================================
# Model 1: Entity (For both Customers & Suppliers)
# ===================================================================
class Entity(OfficeOwned):
    office_unique_fields = ()  # S15 normalised key replaces raw-text uniqueness.
    class EntityType(models.TextChoices):
        CUSTOMER = 'CUSTOMER', 'Πελάτης'
        SUPPLIER = 'SUPPLIER', 'Προμηθευτής'

    class LegalKind(models.TextChoices):
        UNREVIEWED = "UNREVIEWED", "Χρειάζεται επιβεβαίωση"
        INDIVIDUAL = "INDIVIDUAL", "Φυσικό πρόσωπο"
        BUSINESS = "BUSINESS", "Επιχείρηση"

    # Retained as legacy provenance/compatibility; roles below are authoritative.
    entity_type = models.CharField(max_length=10, choices=EntityType.choices, editable=False, verbose_name="Αρχικός τύπος")
    is_customer = models.BooleanField(default=False, verbose_name="Πελάτης")
    is_supplier = models.BooleanField(default=False, verbose_name="Προμηθευτής")
    legal_kind = models.CharField(max_length=12, choices=LegalKind.choices, default=LegalKind.UNREVIEWED, verbose_name="Κατηγορία προσώπου")
    vat_key = models.CharField(max_length=9, default="", editable=False, verbose_name="Κανονικοποιημένος Α.Φ.Μ.")
    is_archived = models.BooleanField(default=False, editable=False, verbose_name="Αρχειοθετημένος")
    archived_at = models.DateTimeField(null=True, editable=False, verbose_name="Αρχειοθετήθηκε")
    archived_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, editable=False,
                                   related_name="archived_counterparties", verbose_name="Αρχειοθετήθηκε από")
    record_version = models.PositiveBigIntegerField(default=0, editable=False, verbose_name="Έκδοση εγγραφής")
    name = models.CharField(max_length=255, verbose_name="Επωνυμία")
    vat_number = models.CharField(max_length=20, blank=True, null=True, verbose_name="Α.Φ.Μ.")
    tax_office = models.CharField(max_length=100, blank=True, verbose_name="Δ.Ο.Υ.")
    address = models.CharField(max_length=255, blank=True, verbose_name="Διεύθυνση")
    city = models.CharField(max_length=100, blank=True, verbose_name="Πόλη")
    postal_code = models.CharField(max_length=10, blank=True, verbose_name="Τ.Κ.")
    phone_number = models.CharField(max_length=20, blank=True, verbose_name="Τηλέφωνο")
    email = models.EmailField(blank=True, verbose_name="Ηλεκτρονική διεύθυνση")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    def __init__(self, *args, **kwargs):
        legacy_only = not args and "entity_type" in kwargs and not {"is_customer", "is_supplier"}.intersection(kwargs)
        super().__init__(*args, **kwargs)
        if legacy_only:
            self.is_customer = self.entity_type == self.EntityType.CUSTOMER
            self.is_supplier = self.entity_type == self.EntityType.SUPPLIER

    def clean(self):
        from .counterparty_validation import contact_values, DUPLICATE_AFM
        from django.core.exceptions import ValidationError
        names = ("name", "vat_number", "tax_office", "address", "city", "postal_code", "phone_number", "email")
        values = contact_values({name: getattr(self, name) for name in names})
        for name, value in values.items():
            setattr(self, name, value)
        self.vat_key = values["vat_number"]
        if not (self.is_customer or self.is_supplier):
            raise ValidationError("Επιλέξτε τουλάχιστον έναν ρόλο: πελάτης ή προμηθευτής.")
        if not self.entity_type:
            self.entity_type = self.EntityType.CUSTOMER if self.is_customer else self.EntityType.SUPPLIER
        if self.vat_key and self.office_id and type(self).objects.filter(office_id=self.office_id, vat_key=self.vat_key).exclude(pk=self.pk).exists():
            raise ValidationError({"vat_number": DUPLICATE_AFM})
        super().clean()

    def save(self, *args, **kwargs):
        self.clean()
        return super().save(*args, **kwargs)
    
    class Meta:
        verbose_name = "Οντότητα (Πελάτης/Προμηθευτής)"
        verbose_name_plural = "Οντότητες (Πελάτες/Προμηθευτές)"
        constraints = [models.UniqueConstraint(fields=["id", "office"], name="entity_id_office_key"),
                       models.UniqueConstraint(fields=["office", "vat_key"], condition=~models.Q(vat_key=""),
                           name="entity_office_afm_key", violation_error_message="Ο Α.Φ.Μ. χρησιμοποιείται ήδη σε αυτό το γραφείο."),
                       models.CheckConstraint(condition=models.Q(is_customer=True) | models.Q(is_supplier=True), name="entity_commercial_role_required"),
                       models.CheckConstraint(condition=models.Q(legal_kind__in=["UNREVIEWED", "INDIVIDUAL", "BUSINESS"]), name="entity_valid_legal_kind"),
                       models.CheckConstraint(condition=~models.Q(name__regex=r"^\s*$"), name="entity_nonempty_name"),
                       models.CheckConstraint(condition=(models.Q(is_archived=False, archived_at__isnull=True, archived_by__isnull=True) |
                           models.Q(is_archived=True, archived_at__isnull=False, archived_by__isnull=False)), name="entity_archive_metadata")]


class CounterpartyEvent(models.Model):
    """Append-only workflow attribution; contact values are deliberately omitted."""
    office = models.ForeignKey("Office", on_delete=models.PROTECT, verbose_name="Γραφείο")
    entity = models.ForeignKey(Entity, on_delete=models.PROTECT, related_name="workspace_events", verbose_name="Συναλλασσόμενος")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, verbose_name="Λογιστής")
    action = models.CharField(max_length=10, choices=[("create", "Δημιουργία"), ("update", "Ενημέρωση"),
        ("archive", "Αρχειοθέτηση"), ("restore", "Επαναφορά")], verbose_name="Ενέργεια")
    version = models.PositiveBigIntegerField(verbose_name="Έκδοση")
    changed_fields = models.JSONField(default=list, verbose_name="Πεδία που άλλαξαν")
    occurred_at = models.DateTimeField(auto_now_add=True, verbose_name="Ημερομηνία")

    class Meta:
        ordering = ["-occurred_at", "-pk"]
        constraints = [models.CheckConstraint(condition=models.Q(action__in=["create", "update", "archive", "restore"]), name="counterparty_valid_event")]
        verbose_name = "Ενέργεια συναλλασσομένου"
        verbose_name_plural = "Ενέργειες συναλλασσομένων"

# ===================================================================
# Model 2: CashAccount (The "Ταμεία")
# ===================================================================
class CashAccount(OfficeOwned):
    office_unique_fields = ("name",)
    name = models.CharField(max_length=100, verbose_name="Όνομα Ταμείου")
    opening_balance = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"), editable=False, verbose_name="Αρχικό Υπόλοιπο")
    is_active = models.BooleanField(default=True, verbose_name="Ενεργό")
    opening_date = models.DateField(null=True, blank=True, editable=False, verbose_name="Ημερομηνία αρχικού υπολοίπου")
    opening_approved_at = models.DateTimeField(null=True, blank=True, editable=False, verbose_name="Καταγραφή έγκρισης")
    legacy_opening = models.BooleanField(default=False, editable=False, verbose_name="Αρχικό ποσό από παλαιά εγγραφή")
    opening_key_digest = models.CharField(max_length=71, blank=True, default='', editable=False)
    opening_payload_digest = models.CharField(max_length=71, blank=True, default='', editable=False)
    record_version = models.PositiveBigIntegerField(default=0, editable=False, verbose_name="Έκδοση εγγραφής")

    def delete(self,*args,**kwargs):
        from django.core.exceptions import ValidationError
        raise ValidationError("Το ταμείο διατηρείται με το ιστορικό του. Χρησιμοποιήστε απενεργοποίηση.")


    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Ταμείο"
        verbose_name_plural = "Ταμεία"
        constraints = [models.CheckConstraint(condition=models.Q(opening_balance__gte=Decimal('-9999999999.99'),opening_balance__lte=Decimal('9999999999.99'),opening_balance=Round('opening_balance',2)),name='s18_cash_opening_cents',violation_error_message='Το ποσό πρέπει να είναι έγκυρο και να έχει έως δύο δεκαδικά ψηφία.'),
                       models.UniqueConstraint(fields=["id", "office"], name="cashaccount_id_office_key"),
                       models.UniqueConstraint(fields=["office", "name"], name="cashaccount_office_name_key"),
                       models.UniqueConstraint(fields=['office','opening_key_digest'],condition=~models.Q(opening_key_digest=''),name='s19_opening_key') ]

# ===================================================================
# Model 3: Category (The "Κατηγορίες")
# ===================================================================
class Category(OfficeOwned):
    name = models.CharField(max_length=100, verbose_name="Όνομα Κατηγορίας")
    parent = models.ForeignKey(
        'self', 
        on_delete=models.PROTECT,
        null=True, 
        blank=True, 
        related_name='subcategories',
        verbose_name="Γονική Κατηγορία"
    )

    is_active = models.BooleanField(default=True, verbose_name="Ενεργή κατηγορία")
    record_version = models.PositiveBigIntegerField(default=0, editable=False, verbose_name="Έκδοση εγγραφής")

    def validate_hierarchy(self):
        from django.core.exceptions import ValidationError
        seen={self.pk} if self.pk else set()
        key=self.parent_id
        for depth in range(64):
            if key is None:return
            if key in seen:raise ValidationError({'parent':"Η ιεραρχία κατηγοριών δεν επιτρέπεται να περιέχει κύκλο."})
            seen.add(key)
            row=type(self).objects.filter(pk=key,office_id=self.office_id).values('parent_id','is_active').first()
            if row is None:raise ValidationError({'parent':"Η γονική κατηγορία δεν είναι διαθέσιμη στο γραφείο."})
            if self.is_active and not row['is_active']:raise ValidationError({'parent':"Επιλέξτε ενεργή γονική κατηγορία."})
            key=row['parent_id']
        raise ValidationError({'parent':"Η ιεραρχία περιορίζεται σε 64 επίπεδα."})

    def clean(self):
        super().clean();self.validate_hierarchy()

    def save(self,*args,**kwargs):
        self.validate_hierarchy()
        return super().save(*args,**kwargs)

    def delete(self,*args,**kwargs):
        from django.core.exceptions import ValidationError
        raise ValidationError("Η κατηγορία διατηρείται με το ιστορικό της. Χρησιμοποιήστε απόσυρση.")

    def __str__(self):
        if self.parent:
            return f"{self.parent.name} -> {self.name}"
        return self.name

    class Meta:
        unique_together = ('office', 'name', 'parent',)
        verbose_name = "Κατηγορία"
        verbose_name_plural = "Κατηγορίες"
        constraints = [models.UniqueConstraint(fields=["id", "office"], name="category_id_office_key"),
            models.UniqueConstraint(fields=['office','name'],condition=models.Q(parent__isnull=True),name='s19_root_category_name',violation_error_message="Υπάρχει ήδη βασική κατηγορία με αυτό το όνομα.")]



# ===================================================================
# Model: Agreement
# ===================================================================
class Agreement(OfficeOwned):
    class AgreementType(models.TextChoices):
        RECEIVABLE = 'RECEIVABLE', 'Receivable (from Customer)'
        PAYABLE = 'PAYABLE', 'Payable (to Supplier)'

    class AgreementStatus(models.TextChoices):
        ACTIVE = 'ACTIVE', 'Active'
        COMPLETED = 'COMPLETED', 'Completed'
        CANCELLED = 'CANCELLED', 'Cancelled'

    agreement_type = models.CharField(max_length=10, choices=AgreementType.choices)
    entity = models.ForeignKey(Entity, on_delete=models.CASCADE, related_name='agreements')
    description = models.CharField(max_length=255, verbose_name="Description of Services/Goods")
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="Total Agreed Amount")
    start_date = models.DateField()
    status = models.CharField(max_length=10, choices=AgreementStatus.choices, default=AgreementStatus.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Συμφωνία με {self.entity.name} για {self.total_amount}€"

    class Meta:
        verbose_name = "Agreement"
        verbose_name_plural = "Agreements"
        ordering = ['-start_date']
        constraints = [models.UniqueConstraint(fields=["id", "office"], name="agreement_id_office_key"),
            models.CheckConstraint(condition=models.Q(total_amount__gt=0,total_amount__lte=Decimal("9999999999.99"),total_amount=Round("total_amount",2)),name="s18_agreement_positive_cents",violation_error_message="Το ποσό πρέπει να είναι έγκυρο και να έχει έως δύο δεκαδικά ψηφία.")]

# ===================================================================
# Model 4: Transaction — immutable cash ledger; services own posting rules
# ===================================================================
class Transaction(OfficeOwned):
    class TransactionType(models.TextChoices):
        INCOME = 'INCOME', 'Έσοδο'
        EXPENSE = 'EXPENSE', 'Έξοδο'
        TRANSFER = 'TRANSFER', 'Μεταφορά'

    transaction_date = models.DateField(verbose_name="Ημερομηνία")
    transaction_type = models.CharField(max_length=10, choices=TransactionType.choices, verbose_name="Τύπος Κίνησης")
    amount = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="Ποσό")
    description = models.CharField(max_length=255, verbose_name="Περιγραφή")
    remarks = models.TextField(blank=True, verbose_name="Πατηρήσεις")
    cash_account = models.ForeignKey(CashAccount, on_delete=models.PROTECT, verbose_name="Ταμείο")
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Κατηγορία")
    entity = models.ForeignKey(Entity, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Πελάτης/Προμηθευτής", related_name='entity_transactions')
    agreement = models.ForeignKey(Agreement, on_delete=models.SET_NULL, null=True, blank=True, related_name='transactions', verbose_name='Συμφωνία')
    transfer_id = models.UUIDField(default=uuid.uuid4, editable=False, verbose_name="Ομάδα μεταφοράς", help_text="Συνδέει τα δύο σκέλη εσωτερικής μεταφοράς")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Καταχωρίστηκε")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Ενημερώθηκε")


    posting_kind = models.CharField(max_length=12,default='LEGACY',editable=False,verbose_name='Είδος καταχώρισης',choices=[
        ('LEGACY','Αρχική/διαχειριστική εγγραφή'),('ORDINARY','Κανονική κίνηση'),
        ('TRANSFER','Εσωτερική μεταφορά'),('REVERSAL','Αντιλογισμός')])
    command = models.ForeignKey('accounting.FinanceCommand',on_delete=models.PROTECT,null=True,editable=False,related_name='entries',verbose_name='Οικονομική ενέργεια')
    reversal_of = models.OneToOneField('self',on_delete=models.PROTECT,null=True,editable=False,related_name='reversal',verbose_name='Αρχική κίνηση αντιλογισμού')

    def save(self,*args,**kwargs):
        from .finance_money import money, IMMUTABLE
        from django.core.exceptions import ValidationError
        self.amount=money(self.amount)
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            old=type(self).objects.get(pk=self.pk)
            fields=[f.attname for f in self._meta.concrete_fields if f.name not in {'updated_at'}]
            if any(getattr(self,name)!=getattr(old,name) for name in fields):raise ValidationError(IMMUTABLE)
            return  # A no-op is harmless; never re-run settlement side effects.
        return super().save(*args,**kwargs)

    def delete(self,*args,**kwargs):
        from .finance_money import IMMUTABLE
        from django.core.exceptions import ValidationError
        raise ValidationError(IMMUTABLE)

    def __str__(self):
        return f"{self.transaction_date} - {self.description} - {self.amount}€"

    class Meta:
        ordering = ['-transaction_date', '-created_at']
        verbose_name = "Κίνηση"
        verbose_name_plural = "Κινήσεις"
        constraints = [models.UniqueConstraint(fields=["id", "office"], name="transaction_id_office_key"),
            models.CheckConstraint(condition=models.Q(amount__gt=0,amount__lte=Decimal('9999999999.99'),amount=Round('amount',2)),name='s18_transaction_positive_cents',violation_error_message='Το ποσό πρέπει να είναι έγκυρο και να έχει έως δύο δεκαδικά ψηφία.'),
            models.CheckConstraint(condition=(models.Q(posting_kind='REVERSAL',reversal_of__isnull=False)|models.Q(posting_kind__in=['LEGACY','ORDINARY','TRANSFER'],reversal_of__isnull=True)),name='s18_reversal_reference')]


class Office(models.Model):
    """S11 membership root. Business-record ownership is introduced in S12."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, verbose_name="Αναγνωριστικό γραφείου")
    name = models.CharField(max_length=255, verbose_name="Επωνυμία γραφείου")
    vat_number = models.CharField(max_length=9, blank=True, verbose_name="Α.Φ.Μ. γραφείου",
        validators=[RegexValidator(r"^[0-9]{9}$", "Ο Α.Φ.Μ. πρέπει να αποτελείται από εννέα ψηφία.")])
    email = models.EmailField(blank=True, verbose_name="Ηλεκτρονική διεύθυνση")
    phone = models.CharField(max_length=30, blank=True, verbose_name="Τηλέφωνο")
    address = models.CharField(max_length=255, blank=True, verbose_name="Διεύθυνση")
    city = models.CharField(max_length=100, blank=True, verbose_name="Πόλη")
    postal_code = models.CharField(max_length=10, blank=True, verbose_name="Ταχυδρομικός κώδικας")
    settings_version = models.PositiveBigIntegerField(default=0, editable=False)
    is_active = models.BooleanField(default=True, verbose_name="Ενεργό γραφείο")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Δημιουργήθηκε")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Ενημερώθηκε")

    class Meta:
        verbose_name = "Λογιστικό γραφείο"
        verbose_name_plural = "Λογιστικά γραφεία"
        constraints = [models.CheckConstraint(condition=~models.Q(name=""), name="office_name_not_empty")]

    def __str__(self):
        return self.name


class AccountantProfile(models.Model):
    class Role(models.TextChoices):
        OWNER = "owner", "Υπεύθυνος γραφείου"
        ACCOUNTANT = "accountant", "Λογιστής"

    id = models.BigAutoField(primary_key=True, verbose_name="Αναγνωριστικό προφίλ")
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="accountant_profile", verbose_name="Χρήστης",
        error_messages={"unique": "Ο χρήστης έχει ήδη προφίλ λογιστή."})
    office = models.ForeignKey(Office, on_delete=models.PROTECT, related_name="accountants",
                              verbose_name="Λογιστικό γραφείο")
    role = models.CharField(max_length=10, choices=Role.choices, verbose_name="Ρόλος")
    is_active = models.BooleanField(default=True, verbose_name="Ενεργό προφίλ")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Δημιουργήθηκε")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Ενημερώθηκε")

    class Meta:
        verbose_name = "Προφίλ λογιστή"
        verbose_name_plural = "Προφίλ λογιστών"
        constraints = [models.CheckConstraint(condition=models.Q(role__in=["owner", "accountant"]),
                                               name="accountant_profile_valid_role"),
                       models.UniqueConstraint(fields=["user", "office"], name="accountant_user_office_key")]

    def __str__(self):
        return f"{self.user.get_username()} — {self.office.name}"


from .auth_models import AuthenticatorDevice, AuthRateBucket, AuthSecurityState, MFARecoveryCode  # noqa: E402,F401
from .office_models import StaffInvitation, OwnershipHandover, OfficeAuditEvent  # noqa: E402,F401

from .finance_models import FinanceCommand, FinanceAuditEvent

from .account_models import CashAdjustment, FinanceStructureLock

from .charge_models import AgreementTermsVersion, Charge

from .settlement_models import SettlementCommand, CashAllocation, AllocationRelease
