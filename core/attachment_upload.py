"""Bound incoming multipart bytes before temporary storage grows past its limit."""
from django.core.exceptions import RequestDataTooBig
from django.core.files.uploadhandler import FileUploadHandler


class BoundedAttachmentUploadHandler(FileUploadHandler):
    chunk_size=64*1024

    def new_file(self,*args,**kwargs):
        super().new_file(*args,**kwargs);self.received=0
        if self.content_length and self.content_length>25_000_000:raise RequestDataTooBig('Το αρχείο υπερβαίνει τα 25 μεγαμπάιτ.')

    def receive_data_chunk(self,raw_data,start):
        self.received+=len(raw_data)
        if self.received>25_000_000:raise RequestDataTooBig('Το αρχείο υπερβαίνει τα 25 μεγαμπάιτ.')
        return raw_data

    def file_complete(self,file_size):return None
