"""Operator-only synthetic file/restore proof in an owned disposable database."""
import base64
import hashlib
import json
import os
import secrets
import sys
import uuid

import django
django.setup()
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError,PermissionDenied
from django.db import connection
from django.test import override_settings
from accounting.attachment_services import upload_attachment,save_category,download_attachment
from accounting.attachment_validation import scan_content
from accounting.models import ClientAttachment,Entity
from accounting.membership import create_accountant_profile,create_office
from accounting.tests_attachment_support import pdf_bytes,docx_bytes,doc_bytes,image_bytes,file
from core.attachment_crypto import unseal

identity=os.environ.get('CR008_VERIFY_ID','')
if len(identity)!=20 or not connection.settings_dict['NAME'].startswith('cr008_'+identity):
    raise SystemExit('The file probe requires its exact owned synthetic database.')


def snapshot():
    result={}
    with connection.cursor() as cursor:
        cursor.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")
        names=[row[0] for row in cursor.fetchall()]
        for name in names:
            quoted=connection.ops.quote_name(name)
            cursor.execute('SELECT count(*),md5(coalesce(string_agg(row_to_json(t)::text,E\'\\n\' ORDER BY row_to_json(t)::text),\'\')) FROM '+quoted+' t')
            count,digest=cursor.fetchone();result[name]=[count,digest]
    return result


def prepare():
    office=create_office(name='ΔΟΚΙΜΑΣΤΙΚΑ ΣΥΝΗΜΜΕΝΑ CR008')
    user=get_user_model().objects.create_user('cr008-synthetic-owner',password=secrets.token_urlsafe(48))
    create_accountant_profile(user_id=user.pk,office_id=office.pk,role='owner')
    person=Entity.objects.create(office=office,name='ΣΥΝΘΕΤΙΚΗ ΚΑΡΤΕΛΑ ΑΡΧΕΙΩΝ',entity_type='CUSTOMER')
    category=save_category(user,name='Συνθετικά δικαιολογητικά')
    bodies=[('pdf',pdf_bytes()),('doc',doc_bytes()),('docx',docx_bytes()),('png',image_bytes()),
        ('jpg',image_bytes('JPEG')),('gif',image_bytes('GIF')),('webp',image_bytes('WEBP')),
        ('tif',image_bytes('TIFF')),('bmp',image_bytes('BMP'))]
    checks={}
    for extension,body in bodies:
        row,_=upload_attachment(user,person.pk,category_id=category.pk,description='Συνθετικό δικαιολογητικό',
            upload=file('sample.'+extension,body),request_key=uuid.uuid4())
        returned,data=download_attachment(user,person.pk,row.pk)
        assert data==body and bytes(row.payload)!=body
        checks[extension]={'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data),'sealed':True}
    nonce=uuid.uuid4()
    row,_=upload_attachment(user,person.pk,category_id=category.pk,description='',upload=file(),request_key=nonce)
    duplicate,replay=upload_attachment(user,person.pk,category_id=category.pk,description='',upload=file(),request_key=nonce)
    assert replay and row.pk==duplicate.pk
    before=ClientAttachment.objects.count()
    # Official harmless antivirus test fixture, assembled only in this isolated process.
    marker=base64.b64decode('WDVPIVAlQEFQWzRcUFpYNTQoUF4pN0NDKTd9JEVJQ0FSLVNUQU5EQVJELUFOVElWSVJVUy1URVNULUZJTEUhJEgrSCo=')
    for data in (marker,pdf_bytes()+b'\n%'+marker+b'\n'):
        try:scan_content(data)
        except ValidationError as error:
            assert error.error_dict['file'][0].code=='infected'
        else:raise RuntimeError('The real scanner did not reject its antivirus test fixture')
    try:upload_attachment(user,person.pk,category_id=category.pk,description='',upload=file(body=pdf_bytes()+b'\n%'+marker+b'\n'),request_key=uuid.uuid4())
    except ValidationError as error:
        assert error.error_dict['file'][0].code=='infected'
    else:raise RuntimeError('Infected file reached accepted storage')
    assert ClientAttachment.objects.count()==before
    with override_settings(ATTACHMENT_SCANNER_HOST=''):
        try:upload_attachment(user,person.pk,category_id=category.pk,description='',upload=file(),request_key=uuid.uuid4())
        except ValidationError:pass
        else:raise RuntimeError('Unavailable scanner accepted a file')
    assert ClientAttachment.objects.count()==before
    return {'formats':checks,'real_eicar_denied':True,'scanner_unavailable_denied':True,
        'replay_without_duplicates':True,'snapshot':snapshot(),'files':before}


def recovered():
    rows=list(ClientAttachment.objects.filter(purged=False))
    hashes={str(row.pk):hashlib.sha256(unseal(row)).hexdigest() for row in rows}
    assert rows and all(hashes[str(row.pk)]==row.content_sha256 for row in rows)
    with override_settings(SECRET_KEY=secrets.token_urlsafe(64),SECRET_KEY_FALLBACKS=[]):
        try:unseal(rows[0])
        except ValidationError:pass
        else:raise RuntimeError('A different recovery key decrypted file bytes')
    return {'snapshot':snapshot(),'files':len(rows),'file_hashes':hashes,'wrong_key_denied':True}


if __name__=='__main__':
    print(json.dumps({'prepare':prepare,'recovered':recovered,'snapshot':snapshot}[sys.argv[1]](),ensure_ascii=False))
