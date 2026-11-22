"""Bounded uploads, isolated content inspection and fail-closed ClamD INSTREAM."""
from datetime import datetime,timezone
import hashlib
import os
from pathlib import Path
import re
import socket
import struct
import subprocess
import sys
import time
import unicodedata

from django.conf import settings
from django.core.exceptions import ValidationError
from django.views.decorators.debug import sensitive_variables

from .attachment_models import FILE_TYPES,MAX_FILE_BYTES


def label(value,field,limit,*,required=True):
    if not isinstance(value,str):raise ValidationError({field:'Γράψτε έγκυρο κείμενο.'})
    value=unicodedata.normalize('NFC',value).strip()
    allowed='\n\t' if field=='description' else ''
    if len(value)>limit or required and not value or any(unicodedata.category(c).startswith('C') and c not in allowed for c in value):
        raise ValidationError({field:'Ελέγξτε το κείμενο και το μήκος του.'})
    return value


@sensitive_variables('__ALL__')
def upload_bytes(upload):
    if upload is None:raise ValidationError({'file':'Επιλέξτε αρχείο.'})
    name=unicodedata.normalize('NFC',str(upload.name))
    if (not name or len(name)>180 or Path(name).name!=name or any(c in name for c in ('/','\\',':','\x00'))
        or any(unicodedata.category(c).startswith('C') for c in name)):
        raise ValidationError({'file':'Το όνομα του αρχείου δεν είναι έγκυρο.'})
    extension=Path(name).suffix.lower().lstrip('.')
    if extension not in FILE_TYPES:raise ValidationError({'file':'Επιτρέπονται έγγραφα και οι αναγραφόμενοι τύποι εικόνων.'})
    chunks=[];size=0
    for part in upload.chunks(64*1024):
        size+=len(part)
        if size>MAX_FILE_BYTES:raise ValidationError({'file':'Το αρχείο υπερβαίνει τα 25 μεγαμπάιτ.'})
        chunks.append(part)
    if not size:raise ValidationError({'file':'Το αρχείο είναι κενό.'})
    payload=b''.join(chunks)
    return name,extension,payload,hashlib.sha256(payload).hexdigest()


@sensitive_variables('__ALL__')
def inspect_content(extension,payload):
    try:
        result=subprocess.run([sys.executable,'-m','core.attachment_inspect',extension],input=payload,
            stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=8,check=False,
            cwd=Path(__file__).resolve().parents[1],env={'PATH':os.defpath,'LANG':'C.UTF-8',
                'PYTHONDONTWRITEBYTECODE':'1','PYTHONNOUSERSITE':'1'})
    except (OSError,subprocess.TimeoutExpired):result=None
    if result is None or result.returncode or result.stdout.strip()!=b'VALID':
        raise ValidationError({'file':'Το περιεχόμενο δεν είναι έγκυρο ή δεν αντιστοιχεί στον τύπο του αρχείου.'})
    return FILE_TYPES[extension]


def read_reply(stream,limit=512,*,deadline=None):
    data=bytearray()
    while len(data)<=limit:
        if deadline is not None:
            remaining=deadline-time.monotonic()
            if remaining<=0:raise TimeoutError()
            stream.settimeout(remaining)
        part=stream.recv(min(128,limit+1-len(data)))
        if not part:break
        data.extend(part)
        if b'\0' in part or b'\n' in part:break
    if len(data)>limit:raise ValueError('Oversized scanner reply')
    return bytes(data).rstrip(b'\0\r\n').decode('ascii')


@sensitive_variables('__ALL__')
def scan_content(payload):
    host=getattr(settings,'ATTACHMENT_SCANNER_HOST','')
    port=getattr(settings,'ATTACHMENT_SCANNER_PORT',3310)
    unavailable='Ο έλεγχος ασφαλείας αρχείων δεν είναι διαθέσιμος. Δοκιμάστε ξανά αργότερα.'
    if not host:raise ValidationError({'file':unavailable})
    deadline=time.monotonic()+12
    try:
        with socket.create_connection((host,port),timeout=2) as stream:
            stream.settimeout(2);stream.sendall(b'zVERSION\0');version=read_reply(stream,deadline=deadline)
        match=re.fullmatch(r'ClamAV ([0-9.\-a-z]+)/([0-9]+)/(.+)',version)
        if not match:raise ValueError('Unexpected scanner identity')
        signature_time=datetime.strptime(match[3],'%a %b %d %H:%M:%S %Y').replace(tzinfo=timezone.utc)
        age=(datetime.now(timezone.utc)-signature_time).total_seconds()
        if not -86400<=age<=7*86400:raise ValueError('Stale signatures')
        remaining=deadline-time.monotonic()
        if remaining<=0:raise TimeoutError()
        with socket.create_connection((host,port),timeout=min(2,remaining)) as stream:
            stream.settimeout(remaining);stream.sendall(b'zINSTREAM\0')
            for start in range(0,len(payload),64*1024):
                remaining=deadline-time.monotonic()
                if remaining<=0:raise TimeoutError()
                stream.settimeout(remaining)
                chunk=payload[start:start+64*1024];stream.sendall(struct.pack('!I',len(chunk))+chunk)
            stream.sendall(struct.pack('!I',0));reply=read_reply(stream,deadline=deadline)
        if reply.endswith(' FOUND'):
            raise ValidationError({'file':ValidationError('Το αρχείο απορρίφθηκε από τον έλεγχο ασφαλείας.',code='infected')})
        if reply!='stream: OK':raise ValueError('Incomplete scan')
        return version
    except (OSError,ValueError,UnicodeError):
        raise ValidationError({'file':unavailable}) from None
