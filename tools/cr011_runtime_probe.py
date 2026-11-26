"""Operator-only synthetic credential and file recovery; never a live-user CLI."""
import json
import os
import re
import secrets
import sys

import cr010_probe as previous
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client
from django.urls import reverse

from accounting.staff_access_models import StaffCredentialRequirement
from accounting.staff_access_services import create_direct_staff,password_marker
from accounting.tests_auth_support import staff_client_login


class ProbeClient(Client):
    def post(self,*args,**kwargs):
        kwargs['secure']=True;kwargs['HTTP_HOST']='cr008.example.invalid'
        return super().post(*args,**kwargs)


def isolated():
    identity=os.environ.get('CR008_VERIFY_ID','')
    name=str(connection.settings_dict['NAME'])
    if not re.fullmatch('[0-9a-f]{20}',identity) or name not in ('cr008_'+identity,'cr008_'+identity+'_recovered') \
            or connection.settings_dict['USER'] != 'cr008_app' or not settings.ATTACHMENT_SCANNER_HOST:
        raise RuntimeError('Credential rehearsal is restricted to its owned synthetic database')
    for key in ('CR011_SYNTHETIC_TEMP_PASSWORD','CR011_SYNTHETIC_PERSONAL_PASSWORD'):
        if len(os.environ.get(key,''))<32:raise RuntimeError('Missing ephemeral synthetic credential')


def prepare():
    isolated()
    if str(connection.settings_dict['NAME']).endswith('_recovered'):raise RuntimeError('Preparation may run only in the owned source database')
    result=previous.prepare()
    owner=get_user_model().objects.get(username='cr008-synthetic-owner')
    owner_password=secrets.token_urlsafe(48);owner.set_password(owner_password);owner.save(update_fields=['password'])
    client=ProbeClient();staff_client_login(client,owner)
    request=client.get(reverse('office-members'),secure=True,HTTP_HOST='cr008.example.invalid').wsgi_request
    temporary=os.environ['CR011_SYNTHETIC_TEMP_PASSWORD'];personal=os.environ['CR011_SYNTHETIC_PERSONAL_PASSWORD']
    for name in ('cr011-pending-staff','cr011-completed-staff'):
        create_direct_staff(request,username=name,temporary_password=temporary,role='accountant',owner_password=owner_password)
        person=get_user_model().objects.get(username=name);browser=Client()
        response=browser.post(reverse('login'),{'username':name,'password':temporary},secure=True,HTTP_HOST='cr008.example.invalid')
        assert response.status_code==302 and response.url==reverse('password-change-required')
        if name=='cr011-completed-staff':
            row=StaffCredentialRequirement.objects.get(user=person)
            response=browser.post(reverse('password-change-required'),{'current_password':temporary,'new_password':personal,
                'new_password_confirm':personal,'version':row.version},secure=True,HTTP_HOST='cr008.example.invalid')
            assert response.status_code==302
            person.refresh_from_db();row.refresh_from_db()
            assert person.check_password(personal) and not person.check_password(temporary) and not row.required
    result['snapshot']=previous.prior.snapshot()
    result['staff_credentials']={'same_office_direct_creation':True,'first_login_forced':True,
        'personal_password_change':True,'passwords_hashed_only':True,'pending_and_completed_rows_in_backup':True}
    return result


def recovered():
    isolated();result=previous.recovered()
    for name,key,required in (('cr011-pending-staff','CR011_SYNTHETIC_TEMP_PASSWORD',True),
            ('cr011-completed-staff','CR011_SYNTHETIC_PERSONAL_PASSWORD',False)):
        user=get_user_model().objects.get(username=name);row=StaffCredentialRequirement.objects.get(user=user)
        assert user.check_password(os.environ[key]) and row.required is required and row.password_marker==password_marker(user)
        assert row.office_id==user.accountant_profile.office_id
    result['staff_credentials_recovered']=True
    return result


if __name__=='__main__':
    isolated()
    print(json.dumps({'prepare':prepare,'recovered':recovered,'snapshot':previous.prior.snapshot}[sys.argv[1]](),ensure_ascii=False))
