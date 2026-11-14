"""Operator-only initial regular owner creation. Never creates a Django admin."""
from getpass import getpass

from django.contrib.auth import get_user_model, password_validation
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email
from django.db import DatabaseError, transaction

from accounting.models import AccountantProfile, Office
from accounting.membership import create_accountant_profile, create_office
from accounting.office_services import audit, email_key, lock_identifiers


class Command(BaseCommand):
    help = "Create the initial regular office owner, with an interactive password and mandatory first-login MFA."

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--new-office-name")
        group.add_argument("--office", type=str)
        parser.add_argument("--username", required=True)
        parser.add_argument("--email", required=True)
        parser.add_argument("--operator", default="", help="Declared person responsible for this initial account")

    def handle(self, **options):
        username = options["username"].strip()
        email = email_key(options["email"])
        try:
            validate_email(email)
            existing = get_user_model().objects.filter(username__iexact=username).first()
            if existing:
                profile = AccountantProfile.objects.select_related("office").filter(user=existing).first()
                correct_office = profile and (str(profile.office_id) == options["office"] if options["office"]
                    else profile.office.name == options["new_office_name"].strip())
                if (correct_office and profile.role == "owner" and profile.is_active and profile.office.is_active
                        and existing.is_active and not existing.is_staff and not existing.is_superuser and email_key(existing.email) == email):
                    self.stdout.write("Ο κανονικός λογαριασμός υπευθύνου υπάρχει ήδη. Δεν άλλαξε κανένα στοιχείο.")
                    return
                raise CommandError("Το όνομα χρήστη χρησιμοποιείται ήδη. Δεν έγινε αλλαγή ή αναβάθμιση λογαριασμού.")
            operator = options["operator"].strip()
            if not operator or len(operator) > 100:
                raise CommandError("Δηλώστε τον υπεύθυνο χειριστή με --operator (έως 100 χαρακτήρες).")
            password = getpass("Κωδικός πρόσβασης: ")
            if password != getpass("Επανάληψη κωδικού: "):
                raise CommandError("Οι κωδικοί δεν συμφωνούν.")
            with transaction.atomic():
                office = (Office.objects.select_for_update().get(pk=options["office"]) if options["office"]
                          else create_office(name=options["new_office_name"]))
                if not office.is_active or AccountantProfile.objects.filter(office=office, role="owner", is_active=True, user__is_active=True).exists():
                    raise CommandError("Το γραφείο είναι ανενεργό ή έχει ήδη υπεύθυνο. Χρησιμοποιήστε την κανονική διαδικασία πρόσκλησης και παράδοσης.")
                lock_identifiers("email:" + email, "username:" + username.casefold())
                if get_user_model().objects.filter(email__iexact=email).exists() or get_user_model().objects.filter(username__iexact=username).exists():
                    raise CommandError("Το όνομα χρήστη ή η ηλεκτρονική διεύθυνση χρησιμοποιείται ήδη.")
                user = get_user_model()(username=username, email=email, is_active=True, is_staff=False, is_superuser=False)
                password_validation.validate_password(password, user=user)
                user.set_password(password); user.full_clean(); user.save(force_insert=True)
                create_accountant_profile(user_id=user.pk, office_id=office.pk, role="owner")
                audit(office, None, "office.bootstrap", target=user, after=("owner", True), operator_ref=operator)
            self.stdout.write("Δημιουργήθηκε κανονικός λογαριασμός εφαρμογής: " + username)
            self.stdout.write("Γραφείο: " + str(office.pk))
            self.stdout.write("Συνδεθείτε στην εφαρμογή και ρυθμίστε την επαλήθευση δύο παραγόντων.")
        except ValidationError as error:
            raise CommandError(" ".join(error.messages)) from None
        except (Office.DoesNotExist, ValueError, DatabaseError):
            raise CommandError("Η δημιουργία δεν ολοκληρώθηκε. Ελέγξτε το γραφείο και τη διαθεσιμότητα των στοιχείων.") from None
