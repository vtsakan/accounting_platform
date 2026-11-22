"""Current office authority, immutable sealed identities and attributed actions."""
from django.db import migrations

FORWARD=r"""
ALTER TABLE accounting_clientattachment ADD CONSTRAINT cr008_file_entity_office
 FOREIGN KEY(entity_id,office_id) REFERENCES accounting_entity(id,office_id) DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE accounting_clientattachment ADD CONSTRAINT cr008_file_category_office
 FOREIGN KEY(category_id,office_id) REFERENCES accounting_attachmentcategory(id,office_id) DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE accounting_clientattachment ADD CONSTRAINT cr008_file_actor_office
 FOREIGN KEY(uploaded_by_id,office_id) REFERENCES accounting_accountantprofile(user_id,office_id) DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE accounting_attachmentevent ADD CONSTRAINT cr008_event_entity_office
 FOREIGN KEY(entity_id,office_id) REFERENCES accounting_entity(id,office_id) DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE accounting_attachmentevent ADD CONSTRAINT cr008_event_file_office
 FOREIGN KEY(attachment_id,office_id) REFERENCES accounting_clientattachment(id,office_id) DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE accounting_attachmentevent ADD CONSTRAINT cr008_event_category_office
 FOREIGN KEY(category_id,office_id) REFERENCES accounting_attachmentcategory(id,office_id) DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE accounting_attachmentevent ADD CONSTRAINT cr008_event_actor_office
 FOREIGN KEY(actor_id,office_id) REFERENCES accounting_accountantprofile(user_id,office_id) DEFERRABLE INITIALLY IMMEDIATE;

CREATE FUNCTION accounting_cr008_actor(office_key uuid,entity_key bigint) RETURNS bigint LANGUAGE plpgsql AS $$
DECLARE actor bigint; mode text; owner_required boolean; archived boolean;
BEGIN
 actor:=nullif(current_setting('accounting.cr008_actor',true),'')::bigint;
 mode:=current_setting('accounting.cr008_action',true);
 IF actor IS NULL OR mode IS NULL THEN RAISE EXCEPTION 'Attachment action requires fresh authority'
  USING ERRCODE='23514',CONSTRAINT='cr008_authority'; END IF;
 owner_required:=mode IN('CATEGORY','REMOVE','PURGE');
 PERFORM id FROM accounting_office WHERE id=office_key AND is_active FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'Active office required' USING ERRCODE='23514',CONSTRAINT='cr008_authority'; END IF;
 PERFORM id FROM auth_user WHERE id=actor AND is_active FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'Active user required' USING ERRCODE='23514',CONSTRAINT='cr008_authority'; END IF;
 PERFORM id FROM accounting_accountantprofile WHERE user_id=actor AND office_id=office_key AND is_active
  AND role IN('owner','accountant') AND (NOT owner_required OR role='owner') FOR KEY SHARE;
 IF NOT FOUND THEN RAISE EXCEPTION 'Same-office role required' USING ERRCODE='23514',CONSTRAINT='cr008_authority'; END IF;
 IF entity_key IS NOT NULL THEN
  SELECT is_archived INTO archived FROM accounting_entity WHERE id=entity_key AND office_id=office_key FOR UPDATE;
  IF NOT FOUND OR EXISTS(SELECT 1 FROM accounting_counterpartydeletion WHERE entity_id=entity_key) THEN
   RAISE EXCEPTION 'Visible same-office client required' USING ERRCODE='23514',CONSTRAINT='cr008_entity'; END IF;
  IF archived AND mode NOT IN('DOWNLOAD','REMOVE','PURGE') THEN
   RAISE EXCEPTION 'Restore the archived client before new work' USING ERRCODE='23514',CONSTRAINT='cr008_archived'; END IF;
  IF mode='PURGE' AND NOT archived THEN RAISE EXCEPTION 'Client deletion requires archive'
   USING ERRCODE='23514',CONSTRAINT='cr008_purge'; END IF;
 END IF;
 RETURN actor;
END $$;

CREATE FUNCTION accounting_cr008_category_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Retire categories instead' USING ERRCODE='23514',CONSTRAINT='cr008_retained'; END IF;
 PERFORM accounting_cr008_actor(NEW.office_id,NULL);
 IF current_setting('accounting.cr008_action')<>'CATEGORY' OR char_length(NEW.name) NOT BETWEEN 1 AND 80
  OR NEW.name<>btrim(NEW.name) OR NEW.name ~ '[[:cntrl:]]'
  OR TG_OP='INSERT' AND NEW.record_version<>0
  OR TG_OP='UPDATE' AND ((NEW.id,NEW.office_id) IS DISTINCT FROM (OLD.id,OLD.office_id) OR NEW.record_version<>OLD.record_version+1) THEN
  RAISE EXCEPTION 'Versioned owner category action required' USING ERRCODE='23514',CONSTRAINT='cr008_category'; END IF;
 NEW.updated_at:=clock_timestamp();RETURN NEW;
END $$;
CREATE TRIGGER cr008_category_guard BEFORE INSERT OR UPDATE OR DELETE ON accounting_attachmentcategory
 FOR EACH ROW EXECUTE FUNCTION accounting_cr008_category_guard();

CREATE FUNCTION accounting_cr008_attachment_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE actor bigint; mode text;
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Retain a content-free identity' USING ERRCODE='23514',CONSTRAINT='cr008_retained'; END IF;
 actor:=accounting_cr008_actor(NEW.office_id,NEW.entity_id);mode:=current_setting('accounting.cr008_action');
 IF TG_OP='UPDATE' AND ((NEW.id,NEW.office_id,NEW.entity_id,NEW.uploaded_by_id,NEW.uploader_label,
      NEW.request_key,NEW.request_digest,NEW.created_at,NEW.scanned_at) IS DISTINCT FROM
     (OLD.id,OLD.office_id,OLD.entity_id,OLD.uploaded_by_id,OLD.uploader_label,
      OLD.request_key,OLD.request_digest,OLD.created_at,OLD.scanned_at) OR OLD.purged OR NEW.record_version<>OLD.record_version+1) THEN
  RAISE EXCEPTION 'Attachment identity is immutable' USING ERRCODE='23514',CONSTRAINT='cr008_identity'; END IF;
 IF TG_OP='INSERT' THEN
  IF mode<>'UPLOAD' OR NEW.uploaded_by_id<>actor OR NEW.record_version<>0 OR NEW.purged THEN
   RAISE EXCEPTION 'Explicit clean upload required' USING ERRCODE='23514',CONSTRAINT='cr008_upload'; END IF;
  SELECT username INTO NEW.uploader_label FROM auth_user WHERE id=actor;
  NEW.created_at:=clock_timestamp();NEW.scanned_at:=clock_timestamp();
 ELSIF mode='EDIT' THEN
  IF (NEW.original_name,NEW.content_type,NEW.content_sha256,NEW.byte_size,NEW.salt,NEW.nonce,NEW.payload,NEW.scan_engine,NEW.purged)
    IS DISTINCT FROM (OLD.original_name,OLD.content_type,OLD.content_sha256,OLD.byte_size,OLD.salt,OLD.nonce,OLD.payload,OLD.scan_engine,OLD.purged) THEN
   RAISE EXCEPTION 'Replacing file bytes requires a new identity' USING ERRCODE='23514',CONSTRAINT='cr008_content'; END IF;
 ELSIF mode NOT IN('REMOVE','PURGE') OR NOT NEW.purged THEN
  RAISE EXCEPTION 'Explicit attachment transition required' USING ERRCODE='23514',CONSTRAINT='cr008_transition';
 END IF;
 IF NEW.purged THEN
  IF NEW.category_id IS NOT NULL OR NEW.original_name<>'' OR NEW.description<>'' OR NEW.content_type<>''
    OR NEW.content_sha256<>'' OR NEW.byte_size<>0 OR octet_length(NEW.payload)<>0 OR octet_length(NEW.salt)<>0
    OR octet_length(NEW.nonce)<>0 OR NEW.scan_engine<>'' THEN
   RAISE EXCEPTION 'Removal must erase all attachment content' USING ERRCODE='23514',CONSTRAINT='cr008_purge'; END IF;
 ELSE
  IF NEW.category_id IS NULL OR NEW.byte_size NOT BETWEEN 1 AND 25000000
    OR octet_length(NEW.payload)<>NEW.byte_size+16 OR octet_length(NEW.salt)<>16 OR octet_length(NEW.nonce)<>12
    OR NEW.content_sha256 !~ '^[0-9a-f]{64}$' OR NEW.request_digest !~ '^[0-9a-f]{64}$'
    OR char_length(NEW.original_name) NOT BETWEEN 1 AND 180 OR NEW.original_name ~ '[[:cntrl:]/\\:]'
    OR NEW.content_type NOT IN('application/pdf','application/msword',
       'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
       'image/png','image/jpeg','image/gif','image/webp','image/tiff','image/bmp')
    OR NEW.scan_engine !~ '^ClamAV [0-9.\-a-z]+/[0-9]+/' OR char_length(NEW.scan_engine)>120 THEN
   RAISE EXCEPTION 'Bounded sealed clean content required' USING ERRCODE='23514',CONSTRAINT='cr008_sealed'; END IF;
  IF NOT EXISTS(SELECT 1 FROM accounting_attachmentcategory WHERE id=NEW.category_id AND office_id=NEW.office_id
     AND (is_active OR TG_OP='UPDATE' AND NEW.category_id=OLD.category_id)) THEN
   RAISE EXCEPTION 'Active same-office category required' USING ERRCODE='23514',CONSTRAINT='cr008_category'; END IF;
 END IF;
 IF char_length(NEW.description)>1000 THEN RAISE EXCEPTION 'Description too long'
  USING ERRCODE='23514',CONSTRAINT='cr008_description'; END IF;
 NEW.updated_at:=clock_timestamp();RETURN NEW;
END $$;
CREATE TRIGGER cr008_attachment_guard BEFORE INSERT OR UPDATE OR DELETE ON accounting_clientattachment
 FOR EACH ROW EXECUTE FUNCTION accounting_cr008_attachment_guard();

CREATE FUNCTION accounting_cr008_event_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE actor bigint; mode text;
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Attachment audit is immutable' USING ERRCODE='23514',CONSTRAINT='cr008_audit'; END IF;
 actor:=accounting_cr008_actor(NEW.office_id,NEW.entity_id);mode:=current_setting('accounting.cr008_action');
 IF NEW.actor_id<>actor OR NEW.action<>mode
  OR mode NOT IN('CATEGORY','UPLOAD','EDIT','DOWNLOAD','REMOVE','PURGE')
  OR mode<>'DOWNLOAD' AND pg_trigger_depth()<2
  OR mode='DOWNLOAD' AND NOT EXISTS(SELECT 1 FROM accounting_clientattachment
       WHERE id=NEW.attachment_id AND office_id=NEW.office_id AND entity_id=NEW.entity_id AND NOT purged) THEN
  RAISE EXCEPTION 'Exact attachment audit transition required' USING ERRCODE='23514',CONSTRAINT='cr008_audit'; END IF;
 IF mode='CATEGORY' AND (NEW.category_id IS NULL OR NEW.attachment_id IS NOT NULL OR NEW.entity_id IS NOT NULL)
  OR mode<>'CATEGORY' AND (NEW.category_id IS NOT NULL OR NEW.attachment_id IS NULL OR NEW.entity_id IS NULL) THEN
  RAISE EXCEPTION 'Exact audit subject required' USING ERRCODE='23514',CONSTRAINT='cr008_audit'; END IF;
 SELECT username INTO NEW.actor_label FROM auth_user WHERE id=actor;
 NEW.occurred_at:=clock_timestamp();RETURN NEW;
END $$;
CREATE TRIGGER cr008_event_guard BEFORE INSERT OR UPDATE OR DELETE ON accounting_attachmentevent
 FOR EACH ROW EXECUTE FUNCTION accounting_cr008_event_guard();

CREATE FUNCTION accounting_cr008_audit() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE actor bigint;
BEGIN
 actor:=nullif(current_setting('accounting.cr008_actor',true),'')::bigint;
 IF TG_TABLE_NAME='accounting_attachmentcategory' THEN
  INSERT INTO accounting_attachmentevent(id,office_id,category_id,actor_id,actor_label,action,occurred_at)
   VALUES(gen_random_uuid(),NEW.office_id,NEW.id,actor,'','CATEGORY',clock_timestamp());
 ELSE
  INSERT INTO accounting_attachmentevent(id,office_id,entity_id,attachment_id,actor_id,actor_label,action,occurred_at)
   VALUES(gen_random_uuid(),NEW.office_id,NEW.entity_id,NEW.id,actor,'',current_setting('accounting.cr008_action'),clock_timestamp());
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER cr008_category_audit AFTER INSERT OR UPDATE ON accounting_attachmentcategory
 FOR EACH ROW EXECUTE FUNCTION accounting_cr008_audit();
CREATE TRIGGER cr008_attachment_audit AFTER INSERT OR UPDATE ON accounting_clientattachment
 FOR EACH ROW EXECUTE FUNCTION accounting_cr008_audit();
"""

REVERSE=r"""
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM accounting_clientattachment) OR EXISTS(SELECT 1 FROM accounting_attachmentcategory) THEN
  RAISE EXCEPTION 'Retain attachment records before any reviewed downgrade'; END IF;
END $$;
DROP TRIGGER cr008_category_audit ON accounting_attachmentcategory;
DROP TRIGGER cr008_attachment_audit ON accounting_clientattachment;
DROP TRIGGER cr008_event_guard ON accounting_attachmentevent;
DROP TRIGGER cr008_attachment_guard ON accounting_clientattachment;
DROP TRIGGER cr008_category_guard ON accounting_attachmentcategory;
DROP FUNCTION accounting_cr008_audit();DROP FUNCTION accounting_cr008_event_guard();
DROP FUNCTION accounting_cr008_attachment_guard();DROP FUNCTION accounting_cr008_category_guard();DROP FUNCTION accounting_cr008_actor(uuid,bigint);
ALTER TABLE accounting_attachmentevent DROP CONSTRAINT cr008_event_actor_office;
ALTER TABLE accounting_attachmentevent DROP CONSTRAINT cr008_event_category_office;
ALTER TABLE accounting_attachmentevent DROP CONSTRAINT cr008_event_file_office;
ALTER TABLE accounting_attachmentevent DROP CONSTRAINT cr008_event_entity_office;
ALTER TABLE accounting_clientattachment DROP CONSTRAINT cr008_file_actor_office;
ALTER TABLE accounting_clientattachment DROP CONSTRAINT cr008_file_category_office;
ALTER TABLE accounting_clientattachment DROP CONSTRAINT cr008_file_entity_office;
"""


class Migration(migrations.Migration):
    dependencies=[('accounting','0035_client_attachments')]
    operations=[migrations.RunSQL(FORWARD,REVERSE)]
