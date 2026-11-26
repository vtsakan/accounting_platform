"""Add a billing choice and an empty initial-selection receipt; no financial backfill."""
from django.conf import settings
from django.db import migrations,models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies=[('accounting','0040_staff_access_guards'),migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations=[
        migrations.AlterField(model_name='agreementtermsversion',name='billing_mode',field=models.CharField(max_length=12,
            choices=[('UNREVIEWED','Σε αναμονή επιλογής'),('ONE_OFF','Εφάπαξ'),('MONTHLY','Ανά ημερολογιακό μήνα'),('ON_DEMAND','Χρεώσεις κατά περίπτωση')],default='UNREVIEWED')),
        migrations.AlterField(model_name='agreementchange',name='billing_mode',field=models.CharField(max_length=12,
            choices=[('ONE_OFF','Εφάπαξ'),('MONTHLY','Ανά ημερολογιακό μήνα'),('ON_DEMAND','Χρεώσεις κατά περίπτωση')])),
        migrations.CreateModel(name='CashChargeSelection',fields=[
            ('source_cash',models.OneToOneField(primary_key=True,serialize=False,related_name='initial_charge_selection',editable=False,
                on_delete=django.db.models.deletion.PROTECT,to='accounting.transaction')),
            ('charge',models.ForeignKey(editable=False,on_delete=django.db.models.deletion.PROTECT,to='accounting.charge')),
            ('settlement',models.OneToOneField(editable=False,on_delete=django.db.models.deletion.PROTECT,to='accounting.settlementcommand')),
            ('actor',models.ForeignKey(editable=False,on_delete=django.db.models.deletion.PROTECT,to=settings.AUTH_USER_MODEL)),
            ('office',models.ForeignKey(editable=False,on_delete=django.db.models.deletion.PROTECT,to='accounting.office',verbose_name='Λογιστικό γραφείο')),
            ('allocated_amount',models.DecimalField(max_digits=12,decimal_places=2,editable=False)),
            ('payload_sha256',models.CharField(max_length=71,editable=False)),
            ('recorded_at',models.DateTimeField(default=django.utils.timezone.now,editable=False)),
        ],options={'verbose_name':'Αρχική επιλογή χρέωσης είσπραξης ή πληρωμής',
            'verbose_name_plural':'Αρχικές επιλογές χρεώσεων εισπράξεων και πληρωμών'}),
    ]
