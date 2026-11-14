"""Operator-only captured invitation; still proves the owner's password and OTP.

This script is supplied through an authenticated, interactive sudo SSH session.
It never enables SMTP in the running service and never creates/approves a member.
"""
from email import policy
from email.parser import BytesParser
from getpass import getpass
from pathlib import Path
import sys
import tempfile
import time

import django
django.setup()
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.sessions.backends.db import SessionStore
from django.test import RequestFactory,override_settings
from accounting.auth_policy import bind_session,reserve_attempt
from accounting.auth_services import password_matches,verify_authenticator
from accounting.capabilities import require_capability
from accounting.office_services import invite_staff


def main():
    username,email,office=sys.argv[1:]
    if not reserve_attempt('manage',username,'operator-cli'):
        raise ValueError('Προσωρινός περιορισμός. Δοκιμάστε ξανά αργότερα.')
    user=get_user_model().objects.get(username=username)
    profile=require_capability(user,'staff.manage')
    if str(profile.office_id)!=office:
        raise ValueError('Το γραφείο διαφέρει από το δοκιμαστικό περιβάλλον.')
    password=getpass('Κωδικός πρόσβασης υπευθύνου: ')
    if not password_matches(user,password):raise ValueError('Τα στοιχεία δεν είναι έγκυρα.')
    request=RequestFactory().post('/office/members/',secure=True,HTTP_HOST=settings.ALLOWED_HOSTS[0])
    request.user=user;request.session=SessionStore();bind_session(request,new_login=True)
    device=verify_authenticator(request,getpass('Νέος, αχρησιμοποίητος κωδικός εφαρμογής επαλήθευσης: '))
    if device is None:raise ValueError('Ο κωδικός επαλήθευσης δεν είναι έγκυρος ή έχει ήδη χρησιμοποιηθεί.')
    user.otp_device=device;user.is_verified=lambda:bool(user.otp_device)
    request.session['s13_mfa_at']=time.time()
    with tempfile.TemporaryDirectory(prefix='demo-invitation-') as temporary:
        with override_settings(AUTH_MAIL_MODE='capture',AUTH_MAIL_CAPTURE_ROOT=temporary):
            invite_staff(request,email,password)
        files=list(Path(temporary).glob('staff-*.eml'))
        if len(files)!=1:raise ValueError('Η πρόσκληση δεν καταγράφηκε.')
        body=BytesParser(policy=policy.default).parsebytes(files[0].read_bytes()).get_body(preferencelist=('plain',)).get_content()
        print(body)
    print('Δεν στάλθηκε πραγματικό email. Ο παραλήπτης εγγράφεται από τον σύνδεσμο και μετά εγκρίνεται από τον υπεύθυνο.')


if __name__=='__main__':
    try:main()
    except Exception as error:
        print(str(error) if type(error) is ValueError else 'Η πρόσκληση δεν ολοκληρώθηκε. Ελέγξτε τον λογαριασμό και την επαλήθευση.',file=sys.stderr)
        sys.exit(1)
