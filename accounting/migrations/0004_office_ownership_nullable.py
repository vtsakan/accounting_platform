from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("accounting", "0003_office_profiles")]
    operations = [
        migrations.AddField(model_name=name, name="office", field=models.ForeignKey(
            to="accounting.office", null=True, editable=False,
            on_delete=django.db.models.deletion.PROTECT, verbose_name="Λογιστικό γραφείο"))
        for name in ("entity", "cashaccount", "category", "agreement", "transaction")
    ]
