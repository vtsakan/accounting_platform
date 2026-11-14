"""S13 authentication metadata. These models have no office/business authority."""
import re
import time

from django.conf import settings
from django.db import models
from django_otp.models import Device, ThrottlingMixin, TimestampMixin
from django_otp.oath import TOTP
from cryptography.fernet import InvalidToken

from core.auth_crypto import cipher, new_salt


class AuthSecurityState(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    revision = models.PositiveBigIntegerField(default=0)
    enrolled_at = models.DateTimeField(null=True, blank=True)


class AuthenticatorDevice(TimestampMixin, ThrottlingMixin, Device):
    encrypted_secret = models.TextField(editable=False)
    secret_salt = models.BinaryField(default=new_salt, editable=False)
    last_t = models.BigIntegerField(default=-1)
    setup_expires_at = models.DateTimeField()

    class Meta:
        verbose_name = "Συσκευή επαλήθευσης"
        verbose_name_plural = "Συσκευές επαλήθευσης"
        constraints = [models.UniqueConstraint(fields=["user"], condition=models.Q(confirmed=True),
                                               name="one_confirmed_authenticator_per_user")]

    @property
    def bin_key(self):
        return cipher(self.user_id, self.secret_salt).decrypt(self.encrypted_secret.encode("ascii"))

    def get_throttle_factor(self):
        return 1

    def verify_token(self, token):
        # Caller must hold select_for_update within an atomic transaction.
        if not self.verify_is_allowed()[0]:
            return False
        valid = False
        if re.fullmatch(r"[0-9]{6}", str(token)):
            try:
                totp = TOTP(self.bin_key, step=30, digits=6)
                totp.time = time.time()
                valid = totp.verify(int(token), tolerance=1, min_t=self.last_t + 1)
            except (InvalidToken, ValueError, UnicodeError):
                valid = False
            if valid:
                self.last_t = totp.t()
                self.throttle_reset(commit=False)
                self.set_last_used_timestamp(commit=False)
                self.save()
        if not valid:
            self.throttle_increment()
        return valid


class MFARecoveryCode(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    digest = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)


class AuthRateBucket(models.Model):
    key = models.CharField(primary_key=True, max_length=64)
    attempts = models.PositiveIntegerField(default=0)
    started_at = models.DateTimeField()
    expires_at = models.DateTimeField(db_index=True)
