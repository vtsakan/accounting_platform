"""Metadata-only, office/client-bound attachment lists with no public file URL."""
from django.core.paginator import Paginator
from django.db import connection
from django.db.models import Q

from .capabilities import require_capability
from .office_access import record
from .models import Entity


def attachments_installed():
    if connection.vendor!='postgresql':return False
    with connection.cursor() as cursor:
        cursor.execute("""SELECT
          (to_regclass('accounting_attachmentcategory') IS NOT NULL)::int+
          (to_regclass('accounting_clientattachment') IS NOT NULL)::int+
          (to_regclass('accounting_attachmentevent') IS NOT NULL)::int,
          (SELECT count(*) FROM django_migrations WHERE app='accounting' AND name IN
            ('0035_client_attachments','0036_attachment_guards')),
          (SELECT count(*) FROM pg_trigger WHERE NOT tgisinternal AND tgenabled='O' AND
            (tgname IN ('cr008_category_guard','cr008_category_audit') AND tgrelid=to_regclass('accounting_attachmentcategory')
             OR tgname IN ('cr008_attachment_guard','cr008_attachment_audit') AND tgrelid=to_regclass('accounting_clientattachment')
             OR tgname='cr008_event_guard' AND tgrelid=to_regclass('accounting_attachmentevent')))""")
        tables,migrations,guards=cursor.fetchone()
    if (tables or migrations or guards) and (tables,migrations,guards)!=(3,2,5):
        raise RuntimeError('Η αναβάθμιση των συνημμένων δεν έχει ολοκληρωθεί.')
    return tables==3


def categories(user,*,active=False):
    from .models import AttachmentCategory
    profile=require_capability(user,'clients.read')
    rows=AttachmentCategory.objects.filter(office_id=profile.office_id)
    return rows.filter(is_active=True) if active else rows


def attachment_rows(user,entity):
    from .models import ClientAttachment
    profile=require_capability(user,'clients.read')
    record(Entity,user,entity.pk)
    return ClientAttachment.objects.filter(office_id=profile.office_id,entity_id=entity.pk,purged=False).defer(
        'payload','salt','nonce').select_related('category')


def card_attachments(user,entity,params):
    if not attachments_installed():return {'attachments_available':False}
    from .attachment_forms import AttachmentFilterForm
    form=AttachmentFilterForm(params,user=user)
    rows=attachment_rows(user,entity)
    if form.is_valid():
        if form.cleaned_data['attachment_category']:rows=rows.filter(category=form.cleaned_data['attachment_category'])
        if form.cleaned_data['attachment_q']:
            q=form.cleaned_data['attachment_q'];rows=rows.filter(Q(original_name__icontains=q)|Q(description__icontains=q))
    else:rows=rows.none()
    page=Paginator(rows,10).get_page(params.get('attachment_page'))
    query=params.copy();query.pop('attachment_page',None)
    return {'attachments_available':True,'attachment_filter':form,'attachment_page':page,
        'attachment_query':query.urlencode(),'can_manage_attachment_categories':require_capability(user,'clients.read').role=='owner'}
