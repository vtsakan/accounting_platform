from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounting.models import CashAccount, Entity

CLIENT_NAME = "ΔΟΚΙΜΑΣΤΙΚΟΣ ΠΕΛΑΤΗΣ S05"
ACCOUNT_NAME = "ΔΟΚΙΜΑΣΤΙΚΟ ΤΑΜΕΙΟ S05"
SYNTHETIC_AFM = "000000000"
OPENING = Decimal("1234.56")


class Command(BaseCommand):
    help = "Create or verify two explicitly synthetic development records; never import real data."

    def handle(self, *args, **options):
        if settings.SETTINGS_MODULE != "core.settings.local":
            raise CommandError("Synthetic development seeding is allowed only with core.settings.local.")
        with transaction.atomic():
            self.seed()
        self.stdout.write("Created or verified the S05 synthetic client and cash account.")

    def seed(self):
        client, _ = Entity.objects.get_or_create(vat_number=SYNTHETIC_AFM, defaults={
            "name": CLIENT_NAME, "entity_type": Entity.EntityType.CUSTOMER,
        })
        account, _ = CashAccount.objects.get_or_create(name=ACCOUNT_NAME, defaults={"opening_balance": OPENING})
        if client.name != CLIENT_NAME or client.entity_type != Entity.EntityType.CUSTOMER or account.opening_balance != OPENING:
            raise CommandError("The synthetic identifiers already contain different data; nothing was overwritten.")
