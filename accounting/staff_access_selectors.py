"""Recognise genuine historical schemas; fail closed after recorded installation."""
from django.db import connection
from django.db.migrations.recorder import MigrationRecorder

from .staff_access_models import StaffCredentialRequirement

FOUNDATION = ('accounting', '0039_staff_access')
GUARDS = ('accounting', '0040_staff_access_guards')


def credentials_installed():
    installed = set(MigrationRecorder(connection).applied_migrations())
    table = StaffCredentialRequirement._meta.db_table
    present = table in connection.introspection.table_names()
    if FOUNDATION not in installed:
        if present:
            raise RuntimeError('Η αναβάθμιση διαχείρισης κωδικών δεν έχει ολοκληρωθεί.')
        return False
    if GUARDS not in installed or not present:
        raise RuntimeError('Η αναβάθμιση διαχείρισης κωδικών δεν έχει ολοκληρωθεί.')
    with connection.cursor() as cursor:
        cursor.execute("SELECT tgenabled FROM pg_trigger WHERE tgrelid=%s::regclass AND tgname='cr011_credential_guard'", [table])
        row = cursor.fetchone()
    if row is None or row[0] != 'O':
        raise RuntimeError('Οι έλεγχοι διαχείρισης κωδικών δεν είναι ενεργοί.')
    return True


def password_change_required(user):
    return bool(user and user.is_authenticated and user.pk is not None and credentials_installed()
        and StaffCredentialRequirement.objects.filter(user_id=user.pk, required=True).exists())
