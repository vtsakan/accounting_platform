import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.migrations.recorder import MigrationRecorder

from accounting.models import CashAccount, Entity
from accounting.management.commands.seed_development_data import ACCOUNT_NAME, CLIENT_NAME, SYNTHETIC_AFM


class Command(BaseCommand):
    help = "Emit non-secret local database/migration and synthetic-marker evidence."

    def add_arguments(self, parser):
        parser.add_argument('--office', help='Explicit office UUID for synthetic marker inspection')

    def handle(self, *args, **options):
        if settings.SETTINGS_MODULE != "core.settings.local":
            raise CommandError("The development probe is allowed only with core.settings.local.")
        with connection.cursor() as cursor:
            cursor.execute("SHOW server_encoding")
            encoding = cursor.fetchone()[0]
        tables = sorted(connection.introspection.table_names())
        applied = sorted(f"{app}.{name}" for app, name in MigrationRecorder(connection).applied_migrations())
        markers = {}
        if options['office'] and {"accounting_entity", "accounting_cashaccount"} <= set(tables):
            client = Entity.objects.filter(office_id=options['office'], vat_number=SYNTHETIC_AFM, name=CLIENT_NAME).first()
            account = CashAccount.objects.filter(office_id=options['office'], name=ACCOUNT_NAME).first()
            if client and account:
                markers = {"client_id": client.pk, "afm": client.vat_number,
                           "greek_name_matches": client.name == CLIENT_NAME, "account_id": account.pk,
                           "opening_balance": str(account.opening_balance)}
        self.stdout.write(json.dumps({"postgresql_version_num": connection.pg_version, "encoding": encoding,
                                      "public_tables": tables, "applied_migrations": applied, "synthetic_markers": markers}, ensure_ascii=False))
