# accounting/models.py

from django.db import models
import uuid
from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.conf import settings
from .ownership import OfficeOwned


# ===================================================================
# Model 1: Entity (For both Customers & Suppliers)
# ===================================================================
class Entity(OfficeOwned):
    office_unique_fields = ("vat_number",)
    class EntityType(models.TextChoices):
        CUSTOMER = 'CUSTOMER', 'Πελάτης'
        SUPPLIER = 'SUPPLIER', 'Προμηθευτής'

    entity_type = models.CharField(max_length=10, choices=EntityType.choices, verbose_name="Τύπος")
    name = models.CharField(max_length=255, verbose_name="Επωνυμία")
    vat_number = models.CharField(max_length=20, blank=True, null=True, verbose_name="Α.Φ.Μ.")
    tax_office = models.CharField(max_length=100, blank=True, verbose_name="Δ.Ο.Υ.")
    address = models.CharField(max_length=255, blank=True, verbose_name="Διεύθυνση")
    city = models.CharField(max_length=100, blank=True, verbose_name="Πόλη")
    postal_code = models.CharField(max_length=10, blank=True, verbose_name="Τ.Κ.")
    phone_number = models.CharField(max_length=20, blank=True, verbose_name="Τηλέφωνο")
    email = models.EmailField(blank=True, verbose_name="Email")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name
    
    class Meta:
        verbose_name = "Οντότητα (Πελάτης/Προμηθευτής)"
        verbose_name_plural = "Οντότητες (Πελάτες/Προμηθευτές)"
        constraints = [models.UniqueConstraint(fields=["id", "office"], name="entity_id_office_key"),
                       models.UniqueConstraint(fields=["office", "vat_number"],
                           condition=models.Q(vat_number__isnull=False) & ~models.Q(vat_number=""),
                           name="entity_office_nonempty_vat_key")]

# ===================================================================
# Model 2: CashAccount (The "Ταμεία")
# ===================================================================
class CashAccount(OfficeOwned):
    office_unique_fields = ("name",)
    name = models.CharField(max_length=100, verbose_name="Όνομα Ταμείου")
    opening_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0.00, verbose_name="Αρχικό Υπόλοιπο")
    is_active = models.BooleanField(default=True, verbose_name="Ενεργό")

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Ταμείο"
        verbose_name_plural = "Ταμεία"
        constraints = [models.UniqueConstraint(fields=["id", "office"], name="cashaccount_id_office_key"),
                       models.UniqueConstraint(fields=["office", "name"], name="cashaccount_office_name_key")]

# ===================================================================
# Model 3: Category (The "Κατηγορίες")
# ===================================================================
class Category(OfficeOwned):
    name = models.CharField(max_length=100, verbose_name="Όνομα Κατηγορίας")
    parent = models.ForeignKey(
        'self', 
        on_delete=models.CASCADE, 
        null=True, 
        blank=True, 
        related_name='subcategories',
        verbose_name="Γονική Κατηγορία"
    )

    def __str__(self):
        if self.parent:
            return f"{self.parent.name} -> {self.name}"
        return self.name

    class Meta:
        unique_together = ('office', 'name', 'parent',)
        verbose_name = "Κατηγορία"
        verbose_name_plural = "Κατηγορίες"
        constraints = [models.UniqueConstraint(fields=["id", "office"], name="category_id_office_key")]



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
        return f"Agreement with {self.entity.name} for {self.total_amount}€"

    class Meta:
        verbose_name = "Agreement"
        verbose_name_plural = "Agreements"
        ordering = ['-start_date']
        constraints = [models.UniqueConstraint(fields=["id", "office"], name="agreement_id_office_key")]

# ===================================================================
# Model 4: Transaction (The Core Ledger) - WITH AUTOMATION
# ===================================================================
class Transaction(OfficeOwned):
    class TransactionType(models.TextChoices):
        INCOME = 'INCOME', 'Έσοδο'
        EXPENSE = 'EXPENSE', 'Έξοδο'
        TRANSFER = 'TRANSFER', 'Μεταφορά'

    # ... (all the fields are the same down to 'agreement') ...
    transaction_date = models.DateField(verbose_name="Ημερομηνία")
    transaction_type = models.CharField(max_length=10, choices=TransactionType.choices, verbose_name="Τύπος Κίνησης")
    amount = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="Ποσό")
    description = models.CharField(max_length=255, verbose_name="Περιγραφή")
    remarks = models.TextField(blank=True, verbose_name="Πατηρήσεις")
    cash_account = models.ForeignKey(CashAccount, on_delete=models.PROTECT, verbose_name="Ταμείο")
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Κατηγορία")
    entity = models.ForeignKey(Entity, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Πελάτης/Προμηθευτής", related_name='entity_transactions')
    agreement = models.ForeignKey(Agreement, on_delete=models.SET_NULL, null=True, blank=True, related_name='transactions')
    transfer_id = models.UUIDField(default=uuid.uuid4, editable=False, help_text="Used to link two transactions for internal transfers")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


    # --- NEW AUTOMATION LOGIC ---
    def save(self, *args, **kwargs):
        # First, run the standard save method to save the transaction itself
        super().save(*args, **kwargs)

        # Now, check if this transaction is linked to an agreement
        if self.agreement:
            # If so, recalculate the balance for that agreement
            associated_agreement = self.agreement
            
            total_payments = associated_agreement.transactions.aggregate(total=Sum('amount'))['total'] or 0
            
            remaining_balance = associated_agreement.total_amount - total_payments

            # If the balance is zero or less, and the status is not already 'Completed'
            if remaining_balance <= 0 and associated_agreement.status != 'COMPLETED':
                # Update the status to 'Completed'
                associated_agreement.status = Agreement.AgreementStatus.COMPLETED
                associated_agreement.save() # Save the change to the agreement

    def __str__(self):
        return f"{self.transaction_date} - {self.description} - {self.amount}€"

    class Meta:
        ordering = ['-transaction_date', '-created_at']
        verbose_name = "Κίνηση"
        verbose_name_plural = "Κινήσεις"
        constraints = [models.UniqueConstraint(fields=["id", "office"], name="transaction_id_office_key")]


class Office(models.Model):
    """S11 membership root. Business-record ownership is introduced in S12."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, verbose_name="Αναγνωριστικό γραφείου")
    name = models.CharField(max_length=255, verbose_name="Επωνυμία γραφείου")
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
                                               name="accountant_profile_valid_role")]

    def __str__(self):
        return f"{self.user.get_username()} — {self.office.name}"
