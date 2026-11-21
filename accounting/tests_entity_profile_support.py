"""Explicit new required inputs for old synthetic HTTP fixtures, no runtime bypass."""
import re
from django.test import Client


class EntityProfileFixtureClient(Client):
    def post(self,path,data=None,*args,**kwargs):
        if data is not None and (path=='/entity/add/' or re.fullmatch(r'/entity/[0-9]+/edit/',path)):
            data=data.copy()
            data.setdefault('contact_status','ACTIVE')
            data.setdefault('person_kind','LEGAL_ENTITY' if data.get('legal_kind')=='BUSINESS' else 'INDIVIDUAL')
        return super().post(path,data,*args,**kwargs)
