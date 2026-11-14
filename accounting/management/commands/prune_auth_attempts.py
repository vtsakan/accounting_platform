from django.core.management.base import BaseCommand
from django.utils import timezone
from accounting.auth_models import AuthRateBucket, AuthenticatorDevice


class Command(BaseCommand):
    help = "Remove expired authentication budgets and expired unconfirmed setup devices."

    def handle(self, **options):
        count, _ = AuthRateBucket.objects.filter(expires_at__lt=timezone.now()).delete()
        devices, _ = AuthenticatorDevice.objects.filter(confirmed=False, setup_expires_at__lt=timezone.now()).delete()
        self.stdout.write(f"Removed expired records: {count + devices}")
