"""Synthetic file fixtures only; production modules never import this module."""
import io
from functools import lru_cache
import struct
import uuid
import zipfile
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from pypdf import PdfWriter
from PIL import Image

from .attachment_services import save_category,upload_attachment
from .counterparty_services import archive_counterparty as archive_service

SCANNER='ClamAV 1.5.0/1/Mon Nov 23 00:00:00 2026'


def archive_for_attachment_fixture(user,key,*,version):
    """Use the actual archive service with its required explicit intent."""
    return archive_service(user,key,version=version,archive=True)


@lru_cache(maxsize=1)
def pdf_bytes():
    writer=PdfWriter();writer.add_blank_page(width=100,height=100);stream=io.BytesIO();writer.write(stream);return stream.getvalue()


@lru_cache(maxsize=1)
def docx_bytes():
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('[Content_Types].xml','<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        archive.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p/></w:body></w:document>')
    return stream.getvalue()


def image_bytes(format='PNG'):
    stream=io.BytesIO();Image.new('RGB',(8,8),'white').save(stream,format);return stream.getvalue()


def doc_bytes():
    free=0xffffffff;end=0xfffffffe
    header=bytearray(512);header[:8]=bytes.fromhex('d0cf11e0a1b11ae1')
    struct.pack_into('<HHHHH',header,24,0x3e,3,0xfffe,9,6)
    struct.pack_into('<IIIIIIIII',header,40,0,1,1,0,4096,end,0,end,0)
    struct.pack_into('<109I',header,76,0,*([free]*108))
    fat=[free]*128;fat[0]=0xfffffffd;fat[1]=end
    for start in (2,10):
        for index in range(start,start+8):fat[index]=index+1 if index<start+7 else end
    directory=bytearray(512)
    def entry(index,name,kind,start,size,left=free,right=free,child=free):
        offset=index*128;encoded=(name+'\0').encode('utf-16le');directory[offset:offset+len(encoded)]=encoded
        struct.pack_into('<HBBIII',directory,offset+64,len(encoded),kind,1,left,right,child)
        struct.pack_into('<IQ',directory,offset+116,start,size)
    entry(0,'Root Entry',5,end,0,child=1);entry(1,'WordDocument',2,2,4096,left=2);entry(2,'0Table',2,10,4096)
    word=bytearray(4096);struct.pack_into('<HH',word,0,0xa5ec,0xc1)
    return bytes(header)+struct.pack('<128I',*fat)+bytes(directory)+bytes(word)+bytes(4096)


def file(name='Δοκιμή.pdf',body=None):return SimpleUploadedFile(name,pdf_bytes() if body is None else body,content_type='application/octet-stream')


def seed_attachment_routes(cls):
    with patch('accounting.attachment_services.inspect_content',return_value='application/pdf'),patch('accounting.attachment_services.scan_content',return_value=SCANNER):
        for suffix in ('a','b'):
            owner=getattr(cls,'owner' if suffix=='a' else 'owner_b');entity=getattr(cls,'entity_'+suffix)
            category=save_category(owner,name='ΔΟΚΙΜΑΣΤΙΚΟΣ ΧΑΡΑΚΤΗΡΙΣΜΟΣ '+suffix)
            row,_=upload_attachment(owner,entity.pk,category_id=category.pk,description='',upload=file(),request_key=uuid.uuid4())
            setattr(cls,'attachment_category_'+suffix,category);setattr(cls,'attachment_'+suffix,row)
