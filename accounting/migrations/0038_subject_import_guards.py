"""Extend current guards; existing notes, money and activity rows stay untouched."""
from django.db import migrations

FORWARD = r"""
CREATE OR REPLACE FUNCTION accounting_cr006_task_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE actor bigint; actor_name text; actor_role text; assignee_name text;
 archived boolean; key uuid; payload text;
BEGIN
 IF TG_OP='DELETE' THEN
  RAISE EXCEPTION 'Task history is retained' USING ERRCODE='23514',CONSTRAINT='cr006_task_retained';
 END IF;
 actor:=nullif(current_setting('accounting.s18_actor',true),'')::bigint;
 key:=nullif(current_setting('accounting.cr006_request',true),'')::uuid;
 payload:=nullif(current_setting('accounting.cr006_payload',true),'');
 IF actor IS NULL OR key IS NULL OR payload IS NULL OR payload !~ '^sha256:[0-9a-f]{64}$' THEN
  RAISE EXCEPTION 'Explicit task actor and request required' USING ERRCODE='23514',CONSTRAINT='cr006_task_context';
 END IF;
 PERFORM id FROM accounting_office WHERE id=NEW.office_id AND is_active FOR UPDATE;
 IF NOT FOUND THEN
  RAISE EXCEPTION 'Active office required' USING ERRCODE='23514',CONSTRAINT='cr006_task_authority';
 END IF;
 SELECT u.username,p.role INTO actor_name,actor_role FROM auth_user u
 JOIN accounting_accountantprofile p ON p.user_id=u.id
 WHERE u.id=actor AND u.is_active AND p.office_id=NEW.office_id AND p.is_active
 AND p.role IN('accountant','owner') FOR KEY SHARE OF u,p;
 IF NOT FOUND THEN
  RAISE EXCEPTION 'Fresh same-office actor required' USING ERRCODE='23514',CONSTRAINT='cr006_task_authority';
 END IF;
 SELECT is_archived INTO archived FROM accounting_entity WHERE id=NEW.entity_id AND office_id=NEW.office_id FOR UPDATE;
 IF NOT FOUND OR EXISTS(SELECT 1 FROM accounting_counterpartydeletion WHERE entity_id=NEW.entity_id) THEN
  RAISE EXCEPTION 'Visible same-office client required' USING ERRCODE='23514',CONSTRAINT='cr006_task_client';
 END IF;
 PERFORM id FROM accounting_counterpartynote WHERE id=NEW.source_note_id AND entity_id=NEW.entity_id
 AND office_id=NEW.office_id FOR KEY SHARE;
 IF NOT FOUND THEN
  RAISE EXCEPTION 'The retained source note must belong to this client' USING ERRCODE='23514',CONSTRAINT='cr006_task_note';
 END IF;
 IF TG_OP='INSERT' OR NEW.assignee_id IS DISTINCT FROM OLD.assignee_id THEN
  SELECT u.username INTO assignee_name FROM auth_user u JOIN accounting_accountantprofile p ON p.user_id=u.id
  WHERE u.id=NEW.assignee_id AND u.is_active AND p.office_id=NEW.office_id AND p.is_active
   AND p.role IN('accountant','owner') FOR KEY SHARE OF u,p;
  IF NOT FOUND THEN
   RAISE EXCEPTION 'Active same-office assignee required' USING ERRCODE='23514',CONSTRAINT='cr006_task_assignee';
  END IF;
  NEW.assignee_label:=assignee_name;
 ELSIF NEW.assignee_label IS DISTINCT FROM OLD.assignee_label THEN
  RAISE EXCEPTION 'Assignment attribution is retained' USING ERRCODE='23514',CONSTRAINT='cr006_task_identity';
 END IF;
 IF TG_OP='INSERT' THEN
  IF archived OR NEW.creator_id IS DISTINCT FROM actor THEN
   RAISE EXCEPTION 'Restore the client before new work' USING ERRCODE='23514',CONSTRAINT='cr006_task_client';
  END IF;
  NEW.created_at:=clock_timestamp(); NEW.creator_label:=actor_name;
  NEW.version:=0; NEW.status:='OPEN'; NEW.completed_at:=NULL; NEW.completed_by_id:=NULL;
 ELSE
  IF (NEW.id,NEW.office_id,NEW.entity_id,NEW.source_note_id,NEW.creator_id,NEW.creator_label,NEW.created_at)
    IS DISTINCT FROM (OLD.id,OLD.office_id,OLD.entity_id,OLD.source_note_id,OLD.creator_id,OLD.creator_label,OLD.created_at) THEN
   RAISE EXCEPTION 'Task identity and source note are immutable' USING ERRCODE='23514',CONSTRAINT='cr006_task_identity';
  END IF;
  IF actor_role<>'owner' AND actor<>OLD.creator_id AND actor<>OLD.assignee_id THEN
   RAISE EXCEPTION 'Only creator, assigned user or owner may change the task'
    USING ERRCODE='23514',CONSTRAINT='cr006_task_authority';
  END IF;
  IF NEW.version<>OLD.version+1 THEN
   RAISE EXCEPTION 'Stale task version' USING ERRCODE='23514',CONSTRAINT='cr006_task_version';
  END IF;
  IF archived AND NOT(OLD.status IN('OPEN','WAIT') AND NEW.status='DONE'
     AND (NEW.body,NEW.due_date,NEW.assignee_id,NEW.subject) IS NOT DISTINCT FROM (OLD.body,OLD.due_date,OLD.assignee_id,OLD.subject)) THEN
   RAISE EXCEPTION 'Restore the client before changing completed work'
    USING ERRCODE='23514',CONSTRAINT='cr006_task_client';
  END IF;
  IF NEW.status IS DISTINCT FROM OLD.status THEN
   IF (NEW.body,NEW.due_date,NEW.assignee_id,NEW.subject) IS DISTINCT FROM (OLD.body,OLD.due_date,OLD.assignee_id,OLD.subject) THEN
    RAISE EXCEPTION 'Status changes are a separate explicit action' USING ERRCODE='23514',CONSTRAINT='cr006_task_status_action';
   END IF;
   IF OLD.status='DONE' AND NEW.status='WAIT' THEN
    RAISE EXCEPTION 'Reopen completed work before setting pending' USING ERRCODE='23514';
   END IF;
   IF NEW.status='DONE' THEN NEW.completed_at:=clock_timestamp(); NEW.completed_by_id:=actor;
   ELSIF NEW.status IN('OPEN','WAIT') THEN NEW.completed_at:=NULL; NEW.completed_by_id:=NULL;
   END IF;
  ELSIF (NEW.completed_at,NEW.completed_by_id) IS DISTINCT FROM (OLD.completed_at,OLD.completed_by_id) THEN
   RAISE EXCEPTION 'Completion attribution is retained' USING ERRCODE='23514',CONSTRAINT='cr006_task_identity';
  END IF;
 END IF;
 NEW.updated_at:=clock_timestamp();
 RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION accounting_cr006_activity_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE actor bigint; actor_name text; n accounting_counterpartynote; key uuid; payload text;
BEGIN
 IF TG_OP<>'INSERT' THEN
  RAISE EXCEPTION 'Task activity is append only' USING ERRCODE='23514',CONSTRAINT='cr006_activity_retained';
 END IF;
 actor:=nullif(current_setting('accounting.s18_actor',true),'')::bigint;
 key:=nullif(current_setting('accounting.cr006_request',true),'')::uuid;
 payload:=nullif(current_setting('accounting.cr006_payload',true),'');
 IF actor IS NULL OR key IS NULL OR payload IS NULL OR payload !~ '^sha256:[0-9a-f]{64}$'
   OR NEW.request_key IS DISTINCT FROM key OR NEW.payload_sha256 IS DISTINCT FROM payload OR NEW.actor_id IS DISTINCT FROM actor THEN
  RAISE EXCEPTION 'Exact actor and request required' USING ERRCODE='23514',CONSTRAINT='cr006_activity_context';
 END IF;
 PERFORM id FROM accounting_office WHERE id=NEW.office_id AND is_active FOR UPDATE;
 IF NOT FOUND THEN
  RAISE EXCEPTION 'Active office required' USING ERRCODE='23514',CONSTRAINT='cr006_activity_authority';
 END IF;
 SELECT u.username INTO actor_name FROM auth_user u JOIN accounting_accountantprofile p ON p.user_id=u.id
 WHERE u.id=actor AND u.is_active AND p.office_id=NEW.office_id AND p.is_active
  AND p.role IN('owner','accountant') FOR KEY SHARE OF u,p;
 IF NOT FOUND THEN
  RAISE EXCEPTION 'Fresh actor required' USING ERRCODE='23514',CONSTRAINT='cr006_activity_authority';
 END IF;
 SELECT * INTO n FROM accounting_counterpartynote WHERE id=NEW.note_id AND office_id=NEW.office_id;
 IF NOT FOUND THEN
  RAISE EXCEPTION 'Same-office note required' USING ERRCODE='23514',CONSTRAINT='cr006_activity_note';
 END IF;
 IF NEW.task_id IS NULL THEN
  IF NEW.action<>'NOTE' OR NEW.task_version IS NOT NULL OR n.actor_id<>actor OR n.request_key<>key THEN
   RAISE EXCEPTION 'Exact note submission required' USING ERRCODE='23514',CONSTRAINT='cr006_activity_note';
  END IF;
  NEW.before:='{}'::jsonb; NEW.after:=jsonb_build_object('body',n.body,'subject',n.subject,'note_id',n.id,'created_at',n.created_at);
 ELSIF pg_trigger_depth()<2 OR NOT EXISTS(SELECT 1 FROM accounting_clienttask t WHERE t.id=NEW.task_id
   AND t.office_id=NEW.office_id AND t.source_note_id=NEW.note_id AND t.version=NEW.task_version) THEN
  RAISE EXCEPTION 'Task activity is generated by its state transition' USING ERRCODE='23514',CONSTRAINT='cr006_activity_transition';
 END IF;
 NEW.actor_label:=actor_name; NEW.created_at:=clock_timestamp();
 RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION accounting_cr006_task_activity() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE action_name text; previous jsonb;
BEGIN
 IF TG_OP='INSERT' THEN action_name:='CREATE'; previous:='{}'::jsonb;
 ELSE
  previous:=to_jsonb(OLD);
  IF OLD.status<>NEW.status THEN
   action_name:=CASE NEW.status WHEN 'DONE' THEN 'COMPLETE' WHEN 'WAIT' THEN 'PENDING' ELSE CASE OLD.status WHEN 'WAIT' THEN 'RESUME' ELSE 'REOPEN' END END;
  ELSE action_name:='UPDATE'; END IF;
 END IF;
 INSERT INTO accounting_clienttaskactivity(id,office_id,task_id,note_id,request_key,payload_sha256,
  actor_id,actor_label,action,task_version,before,after,created_at)
 VALUES(gen_random_uuid(),NEW.office_id,NEW.id,NEW.source_note_id,
  current_setting('accounting.cr006_request')::uuid,current_setting('accounting.cr006_payload'),
  current_setting('accounting.s18_actor')::bigint,'',action_name,NEW.version,previous,to_jsonb(NEW),clock_timestamp());
 RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION accounting_cr006_archive_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE entity_key bigint;
BEGIN
 IF TG_TABLE_NAME='accounting_entity' THEN
  IF OLD.is_archived OR NOT NEW.is_archived THEN RETURN NEW; END IF;
  entity_key:=NEW.id;
 ELSE entity_key:=NEW.entity_id;
 END IF;
 IF EXISTS(SELECT 1 FROM accounting_clienttask WHERE entity_id=entity_key AND status IN('OPEN','WAIT')) THEN
  RAISE EXCEPTION 'Complete open tasks before archiving or deleting the client'
   USING ERRCODE='23514',CONSTRAINT='cr006_open_tasks';
 END IF;
 RETURN NEW;
END $$;
ALTER TABLE accounting_counterpartynote ADD CONSTRAINT cr010_note_subject CHECK(subject !~ '[[:cntrl:]]' AND char_length(subject)<=200);
ALTER TABLE accounting_clienttask ADD CONSTRAINT cr010_task_subject CHECK(subject !~ '[[:cntrl:]]' AND char_length(subject)<=200);

CREATE FUNCTION accounting_cr010_actor(office_key uuid) RETURNS bigint LANGUAGE plpgsql AS $$
DECLARE actor bigint;
BEGIN
 actor:=nullif(current_setting('accounting.s18_actor',true),'')::bigint;
 PERFORM id FROM accounting_office WHERE id=office_key AND is_active FOR UPDATE;
 IF NOT FOUND OR actor IS NULL THEN RAISE EXCEPTION 'Import requires active office and actor' USING ERRCODE='23514'; END IF;
 PERFORM u.id FROM auth_user u JOIN accounting_accountantprofile p ON p.user_id=u.id
 WHERE u.id=actor AND u.is_active AND p.is_active AND p.office_id=office_key AND p.role IN('owner','accountant') FOR KEY SHARE OF u,p;
 IF NOT FOUND THEN RAISE EXCEPTION 'Fresh same-office accountant required' USING ERRCODE='23514'; END IF;
 RETURN actor;
END $$;

CREATE FUNCTION accounting_cr010_receipt_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE actor bigint;
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Creation receipts are retained' USING ERRCODE='23514'; END IF;
 actor:=accounting_cr010_actor(NEW.office_id);
 IF NEW.actor_id IS DISTINCT FROM actor OR NEW.payload_sha256 !~ '^sha256:[0-9a-f]{64}$' THEN
  RAISE EXCEPTION 'Exact creation actor and payload required' USING ERRCODE='23514';
 END IF;
 PERFORM id FROM accounting_agreement WHERE id=NEW.agreement_id AND office_id=NEW.office_id FOR KEY SHARE;
 IF NOT FOUND OR EXISTS(SELECT 1 FROM accounting_charge WHERE agreement_id=NEW.agreement_id) THEN
  RAISE EXCEPTION 'Receipt requires new same-office terms without a charge' USING ERRCODE='23514';
 END IF;
 NEW.created_at:=clock_timestamp(); RETURN NEW;
END $$;
CREATE TRIGGER cr010_receipt_guard BEFORE INSERT OR UPDATE OR DELETE ON accounting_agreementcreationreceipt
 FOR EACH ROW EXECUTE FUNCTION accounting_cr010_receipt_guard();

CREATE FUNCTION accounting_cr010_import_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE actor bigint;
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Import receipt is retained' USING ERRCODE='23514'; END IF;
 actor:=accounting_cr010_actor(NEW.office_id);
 IF NEW.actor_id IS DISTINCT FROM actor OR NEW.source_sha256 !~ '^sha256:[0-9a-f]{64}$' THEN
  RAISE EXCEPTION 'Exact import actor and source required' USING ERRCODE='23514';
 END IF;
 IF TG_OP='INSERT' THEN
  NEW.created_at:=clock_timestamp();
  IF NEW.state<>'PREVIEW' OR NEW.completed_at IS NOT NULL OR NEW.decisions_sha256<>'' OR NEW.outcome<>'{}'::jsonb
    OR octet_length(NEW.salt)<>16 OR octet_length(NEW.payload) NOT BETWEEN 1 AND 16000000
    OR NEW.expires_at<=NEW.created_at OR NEW.expires_at>NEW.created_at+interval '30 minutes' THEN
   RAISE EXCEPTION 'Bounded sealed preview required' USING ERRCODE='23514';
  END IF;
 ELSE
  IF OLD.state<>'PREVIEW' OR (NEW.id,NEW.office_id,NEW.actor_id,NEW.source_sha256,NEW.created_at,NEW.expires_at)
    IS DISTINCT FROM (OLD.id,OLD.office_id,OLD.actor_id,OLD.source_sha256,OLD.created_at,OLD.expires_at) THEN
   RAISE EXCEPTION 'Import identity and final receipt are immutable' USING ERRCODE='23514';
  END IF;
  IF NEW.state NOT IN('DONE','CANCELLED') OR octet_length(NEW.payload)<>0 OR octet_length(NEW.salt)<>0 THEN
   RAISE EXCEPTION 'Finishing an import purges its sealed preview' USING ERRCODE='23514';
  END IF;
  IF NEW.state='DONE' AND (OLD.expires_at<=clock_timestamp() OR NEW.decisions_sha256 !~ '^sha256:[0-9a-f]{64}$'
     OR jsonb_typeof(NEW.outcome)<>'object' OR NOT(NEW.outcome ?& ARRAY['created','updated','skipped','notes'])
     OR (NEW.outcome-ARRAY['created','updated','skipped','notes'])<>'{}'::jsonb) THEN
   RAISE EXCEPTION 'Reviewed unexpired import result required' USING ERRCODE='23514';
  END IF;
  NEW.completed_at:=clock_timestamp();
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER cr010_import_guard BEFORE INSERT OR UPDATE OR DELETE ON accounting_counterpartyimport
 FOR EACH ROW EXECUTE FUNCTION accounting_cr010_import_guard();

"""

REVERSE = r"""

DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM accounting_counterpartynote WHERE subject<>'')
  OR EXISTS(SELECT 1 FROM accounting_clienttask WHERE subject<>'' OR status='WAIT')
  OR EXISTS(SELECT 1 FROM accounting_agreementcreationreceipt)
  OR EXISTS(SELECT 1 FROM accounting_counterpartyimport) THEN
  RAISE EXCEPTION 'Retain CR010 subjects, states and receipts; no unreviewed downgrade';
 END IF;
END $$;
DROP TRIGGER cr010_import_guard ON accounting_counterpartyimport;
DROP FUNCTION accounting_cr010_import_guard();
DROP TRIGGER cr010_receipt_guard ON accounting_agreementcreationreceipt;
DROP FUNCTION accounting_cr010_receipt_guard();
DROP FUNCTION accounting_cr010_actor(uuid);
ALTER TABLE accounting_counterpartynote DROP CONSTRAINT cr010_note_subject;
ALTER TABLE accounting_clienttask DROP CONSTRAINT cr010_task_subject;
CREATE OR REPLACE FUNCTION accounting_cr006_task_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE actor bigint; actor_name text; actor_role text; assignee_name text;
 archived boolean; key uuid; payload text;
BEGIN
 IF TG_OP='DELETE' THEN
  RAISE EXCEPTION 'Task history is retained' USING ERRCODE='23514',CONSTRAINT='cr006_task_retained';
 END IF;
 actor:=nullif(current_setting('accounting.s18_actor',true),'')::bigint;
 key:=nullif(current_setting('accounting.cr006_request',true),'')::uuid;
 payload:=nullif(current_setting('accounting.cr006_payload',true),'');
 IF actor IS NULL OR key IS NULL OR payload IS NULL OR payload !~ '^sha256:[0-9a-f]{64}$' THEN
  RAISE EXCEPTION 'Explicit task actor and request required' USING ERRCODE='23514',CONSTRAINT='cr006_task_context';
 END IF;
 PERFORM id FROM accounting_office WHERE id=NEW.office_id AND is_active FOR UPDATE;
 IF NOT FOUND THEN
  RAISE EXCEPTION 'Active office required' USING ERRCODE='23514',CONSTRAINT='cr006_task_authority';
 END IF;
 SELECT u.username,p.role INTO actor_name,actor_role FROM auth_user u
 JOIN accounting_accountantprofile p ON p.user_id=u.id
 WHERE u.id=actor AND u.is_active AND p.office_id=NEW.office_id AND p.is_active
 AND p.role IN('accountant','owner') FOR KEY SHARE OF u,p;
 IF NOT FOUND THEN
  RAISE EXCEPTION 'Fresh same-office actor required' USING ERRCODE='23514',CONSTRAINT='cr006_task_authority';
 END IF;
 SELECT is_archived INTO archived FROM accounting_entity WHERE id=NEW.entity_id AND office_id=NEW.office_id FOR UPDATE;
 IF NOT FOUND OR EXISTS(SELECT 1 FROM accounting_counterpartydeletion WHERE entity_id=NEW.entity_id) THEN
  RAISE EXCEPTION 'Visible same-office client required' USING ERRCODE='23514',CONSTRAINT='cr006_task_client';
 END IF;
 PERFORM id FROM accounting_counterpartynote WHERE id=NEW.source_note_id AND entity_id=NEW.entity_id
 AND office_id=NEW.office_id FOR KEY SHARE;
 IF NOT FOUND THEN
  RAISE EXCEPTION 'The retained source note must belong to this client' USING ERRCODE='23514',CONSTRAINT='cr006_task_note';
 END IF;
 IF TG_OP='INSERT' OR NEW.assignee_id IS DISTINCT FROM OLD.assignee_id THEN
  SELECT u.username INTO assignee_name FROM auth_user u JOIN accounting_accountantprofile p ON p.user_id=u.id
  WHERE u.id=NEW.assignee_id AND u.is_active AND p.office_id=NEW.office_id AND p.is_active
   AND p.role IN('accountant','owner') FOR KEY SHARE OF u,p;
  IF NOT FOUND THEN
   RAISE EXCEPTION 'Active same-office assignee required' USING ERRCODE='23514',CONSTRAINT='cr006_task_assignee';
  END IF;
  NEW.assignee_label:=assignee_name;
 ELSIF NEW.assignee_label IS DISTINCT FROM OLD.assignee_label THEN
  RAISE EXCEPTION 'Assignment attribution is retained' USING ERRCODE='23514',CONSTRAINT='cr006_task_identity';
 END IF;
 IF TG_OP='INSERT' THEN
  IF archived OR NEW.creator_id IS DISTINCT FROM actor THEN
   RAISE EXCEPTION 'Restore the client before new work' USING ERRCODE='23514',CONSTRAINT='cr006_task_client';
  END IF;
  NEW.created_at:=clock_timestamp(); NEW.creator_label:=actor_name;
  NEW.version:=0; NEW.status:='OPEN'; NEW.completed_at:=NULL; NEW.completed_by_id:=NULL;
 ELSE
  IF (NEW.id,NEW.office_id,NEW.entity_id,NEW.source_note_id,NEW.creator_id,NEW.creator_label,NEW.created_at)
    IS DISTINCT FROM (OLD.id,OLD.office_id,OLD.entity_id,OLD.source_note_id,OLD.creator_id,OLD.creator_label,OLD.created_at) THEN
   RAISE EXCEPTION 'Task identity and source note are immutable' USING ERRCODE='23514',CONSTRAINT='cr006_task_identity';
  END IF;
  IF actor_role<>'owner' AND actor<>OLD.creator_id AND actor<>OLD.assignee_id THEN
   RAISE EXCEPTION 'Only creator, assigned user or owner may change the task'
    USING ERRCODE='23514',CONSTRAINT='cr006_task_authority';
  END IF;
  IF NEW.version<>OLD.version+1 THEN
   RAISE EXCEPTION 'Stale task version' USING ERRCODE='23514',CONSTRAINT='cr006_task_version';
  END IF;
  IF archived AND NOT(OLD.status='OPEN' AND NEW.status='DONE'
     AND (NEW.body,NEW.due_date,NEW.assignee_id) IS NOT DISTINCT FROM (OLD.body,OLD.due_date,OLD.assignee_id)) THEN
   RAISE EXCEPTION 'Restore the client before changing completed work'
    USING ERRCODE='23514',CONSTRAINT='cr006_task_client';
  END IF;
  IF NEW.status IS DISTINCT FROM OLD.status THEN
   IF (NEW.body,NEW.due_date,NEW.assignee_id) IS DISTINCT FROM (OLD.body,OLD.due_date,OLD.assignee_id) THEN
    RAISE EXCEPTION 'Status changes are a separate explicit action' USING ERRCODE='23514',CONSTRAINT='cr006_task_status_action';
   END IF;
   IF NEW.status='DONE' THEN NEW.completed_at:=clock_timestamp(); NEW.completed_by_id:=actor;
   ELSIF NEW.status='OPEN' THEN NEW.completed_at:=NULL; NEW.completed_by_id:=NULL;
   END IF;
  ELSIF (NEW.completed_at,NEW.completed_by_id) IS DISTINCT FROM (OLD.completed_at,OLD.completed_by_id) THEN
   RAISE EXCEPTION 'Completion attribution is retained' USING ERRCODE='23514',CONSTRAINT='cr006_task_identity';
  END IF;
 END IF;
 NEW.updated_at:=clock_timestamp();
 RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION accounting_cr006_activity_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE actor bigint; actor_name text; n accounting_counterpartynote; key uuid; payload text;
BEGIN
 IF TG_OP<>'INSERT' THEN
  RAISE EXCEPTION 'Task activity is append only' USING ERRCODE='23514',CONSTRAINT='cr006_activity_retained';
 END IF;
 actor:=nullif(current_setting('accounting.s18_actor',true),'')::bigint;
 key:=nullif(current_setting('accounting.cr006_request',true),'')::uuid;
 payload:=nullif(current_setting('accounting.cr006_payload',true),'');
 IF actor IS NULL OR key IS NULL OR payload IS NULL OR payload !~ '^sha256:[0-9a-f]{64}$'
   OR NEW.request_key IS DISTINCT FROM key OR NEW.payload_sha256 IS DISTINCT FROM payload OR NEW.actor_id IS DISTINCT FROM actor THEN
  RAISE EXCEPTION 'Exact actor and request required' USING ERRCODE='23514',CONSTRAINT='cr006_activity_context';
 END IF;
 PERFORM id FROM accounting_office WHERE id=NEW.office_id AND is_active FOR UPDATE;
 IF NOT FOUND THEN
  RAISE EXCEPTION 'Active office required' USING ERRCODE='23514',CONSTRAINT='cr006_activity_authority';
 END IF;
 SELECT u.username INTO actor_name FROM auth_user u JOIN accounting_accountantprofile p ON p.user_id=u.id
 WHERE u.id=actor AND u.is_active AND p.office_id=NEW.office_id AND p.is_active
  AND p.role IN('owner','accountant') FOR KEY SHARE OF u,p;
 IF NOT FOUND THEN
  RAISE EXCEPTION 'Fresh actor required' USING ERRCODE='23514',CONSTRAINT='cr006_activity_authority';
 END IF;
 SELECT * INTO n FROM accounting_counterpartynote WHERE id=NEW.note_id AND office_id=NEW.office_id;
 IF NOT FOUND THEN
  RAISE EXCEPTION 'Same-office note required' USING ERRCODE='23514',CONSTRAINT='cr006_activity_note';
 END IF;
 IF NEW.task_id IS NULL THEN
  IF NEW.action<>'NOTE' OR NEW.task_version IS NOT NULL OR n.actor_id<>actor OR n.request_key<>key THEN
   RAISE EXCEPTION 'Exact note submission required' USING ERRCODE='23514',CONSTRAINT='cr006_activity_note';
  END IF;
  NEW.before:='{}'::jsonb; NEW.after:=jsonb_build_object('body',n.body,'note_id',n.id,'created_at',n.created_at);
 ELSIF pg_trigger_depth()<2 OR NOT EXISTS(SELECT 1 FROM accounting_clienttask t WHERE t.id=NEW.task_id
   AND t.office_id=NEW.office_id AND t.source_note_id=NEW.note_id AND t.version=NEW.task_version) THEN
  RAISE EXCEPTION 'Task activity is generated by its state transition' USING ERRCODE='23514',CONSTRAINT='cr006_activity_transition';
 END IF;
 NEW.actor_label:=actor_name; NEW.created_at:=clock_timestamp();
 RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION accounting_cr006_task_activity() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE action_name text; previous jsonb;
BEGIN
 IF TG_OP='INSERT' THEN action_name:='CREATE'; previous:='{}'::jsonb;
 ELSE
  previous:=to_jsonb(OLD);
  IF OLD.status<>NEW.status THEN
   action_name:=CASE NEW.status WHEN 'DONE' THEN 'COMPLETE' ELSE 'REOPEN' END;
  ELSE action_name:='UPDATE'; END IF;
 END IF;
 INSERT INTO accounting_clienttaskactivity(id,office_id,task_id,note_id,request_key,payload_sha256,
  actor_id,actor_label,action,task_version,before,after,created_at)
 VALUES(gen_random_uuid(),NEW.office_id,NEW.id,NEW.source_note_id,
  current_setting('accounting.cr006_request')::uuid,current_setting('accounting.cr006_payload'),
  current_setting('accounting.s18_actor')::bigint,'',action_name,NEW.version,previous,to_jsonb(NEW),clock_timestamp());
 RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION accounting_cr006_archive_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE entity_key bigint;
BEGIN
 IF TG_TABLE_NAME='accounting_entity' THEN
  IF OLD.is_archived OR NOT NEW.is_archived THEN RETURN NEW; END IF;
  entity_key:=NEW.id;
 ELSE entity_key:=NEW.entity_id;
 END IF;
 IF EXISTS(SELECT 1 FROM accounting_clienttask WHERE entity_id=entity_key AND status='OPEN') THEN
  RAISE EXCEPTION 'Complete open tasks before archiving or deleting the client'
   USING ERRCODE='23514',CONSTRAINT='cr006_open_tasks';
 END IF;
 RETURN NEW;
END $$;
"""

class Migration(migrations.Migration):
    dependencies = [('accounting', '0037_subjects_pending_import')]
    operations = [migrations.RunSQL(FORWARD, REVERSE)]
