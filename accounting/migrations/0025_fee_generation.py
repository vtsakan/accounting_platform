import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('accounting','0024_fee_configuration_guards'), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.CreateModel(name='FeeAutomationVersion', fields=[
            ('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),
            ('office',models.ForeignKey(editable=False,on_delete=django.db.models.deletion.PROTECT,to='accounting.office',verbose_name='Λογιστικό γραφείο')),
            ('schedule',models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,related_name='automations',to='accounting.feeschedule')),
            ('revision',models.PositiveIntegerField()),('enabled',models.BooleanField(default=False)),('first_period',models.DateField()),
            ('actor',models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,to=settings.AUTH_USER_MODEL)),
            ('reason',models.CharField(max_length=500)),('recorded_at',models.DateTimeField(default=django.utils.timezone.now))],
            options={'ordering':['-revision'],'verbose_name':'Έκδοση εξουσιοδότησης αυτόματης χρέωσης',
                'constraints':[models.UniqueConstraint(fields=('schedule','revision'),name='s28_automation_revision')]}),
        migrations.CreateModel(name='FeeGenerationRun',fields=[
            ('office',models.ForeignKey(editable=False,on_delete=django.db.models.deletion.PROTECT,to='accounting.office',verbose_name='Λογιστικό γραφείο')),
            ('job',models.OneToOneField(primary_key=True,serialize=False,on_delete=django.db.models.deletion.PROTECT,related_name='fee_run',to='accounting.backgroundjob')),
            ('schedule',models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,related_name='generation_runs',to='accounting.feeschedule')),
            ('period',models.DateField()),
            ('automation',models.ForeignKey(null=True,blank=True,on_delete=django.db.models.deletion.PROTECT,related_name='runs',to='accounting.feeautomationversion')),
            ('source_key',models.CharField(max_length=120)),
            ('outcome',models.CharField(max_length=12,default='pending',choices=[('pending','Σε αναμονή'),('generated','Δημιουργήθηκε χρέωση'),
                ('existing','Η πηγή έχει ήδη καταχωριστεί'),('outside','Εκτός ενεργού προγράμματος'),('blocked','Μη ενεργός πελάτης ή όροι'),
                ('review','Απαιτείται έλεγχος'),('closed','Κλεισμένη περίοδος'),('future','Δεν έφτασε η έναρξη'),
                ('superseded','Η εξουσιοδότηση άλλαξε'),('paused','Η αυτόματη εκτέλεση είναι ανενεργή')])),
            ('charge',models.ForeignKey(null=True,blank=True,on_delete=django.db.models.deletion.PROTECT,to='accounting.charge')),
            ('recorded_at',models.DateTimeField(default=django.utils.timezone.now))],
            options={'verbose_name':'Αποτέλεσμα μηνιαίας δημιουργίας χρέωσης','constraints':[
                models.UniqueConstraint(fields=('automation','period'),name='s28_auto_period_once'),
                models.CheckConstraint(condition=models.Q(outcome__in=['pending','generated','existing','outside','blocked','review','closed','future','superseded','paused']),name='s28_run_outcome'),
                models.CheckConstraint(condition=(models.Q(outcome__in=['generated','existing'],charge__isnull=False) |
                    (~models.Q(outcome__in=['generated','existing']) & models.Q(charge__isnull=True))),name='s28_run_charge_shape')]})]
