"""Same-office fiscal/credential guards and content-free immutable audit."""
from django.db import migrations

FORWARD = r"""
ALTER TABLE accounting_entityprofile ADD CONSTRAINT cr007_profile_office
 FOREIGN KEY(entity_id,office_id) REFERENCES accounting_entity(id,office_id) DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE accounting_taxiscredential ADD CONSTRAINT cr007_credential_office
 FOREIGN KEY(entity_id,office_id) REFERENCES accounting_entity(id,office_id) DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE accounting_entityprofileevent ADD CONSTRAINT cr007_event_office
 FOREIGN KEY(entity_id,office_id) REFERENCES accounting_entity(id,office_id) DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE accounting_entityprofileevent ADD CONSTRAINT cr007_event_actor
 FOREIGN KEY(actor_id,office_id) REFERENCES accounting_accountantprofile(user_id,office_id) DEFERRABLE INITIALLY IMMEDIATE;
CREATE FUNCTION accounting_cr007_actor(scope uuid, party bigint) RETURNS bigint LANGUAGE plpgsql AS $$
DECLARE actor bigint; role_name text; person accounting_entity; mode text;
BEGIN
 actor:=nullif(current_setting('accounting.s18_actor',true),'')::bigint;
 mode:=nullif(current_setting('accounting.cr007_action',true),'');
 IF actor IS NULL OR mode IS NULL OR mode NOT IN('EDIT','REVEAL','PURGE') THEN
  RAISE EXCEPTION 'Explicit fiscal action required' USING ERRCODE='23514',CONSTRAINT='cr007_context';
 END IF;
 PERFORM id FROM accounting_office WHERE id=scope AND is_active FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'Active office required' USING ERRCODE='23514',CONSTRAINT='cr007_authority'; END IF;
 SELECT p.role INTO role_name FROM auth_user u JOIN accounting_accountantprofile p ON p.user_id=u.id
 WHERE u.id=actor AND u.is_active AND p.office_id=scope AND p.is_active AND p.role IN('owner','accountant')
 FOR KEY SHARE OF u,p;
 IF NOT FOUND THEN RAISE EXCEPTION 'Fresh same-office actor required' USING ERRCODE='23514',CONSTRAINT='cr007_authority'; END IF;
 SELECT * INTO person FROM accounting_entity WHERE id=party AND office_id=scope FOR UPDATE;
 IF NOT FOUND OR EXISTS(SELECT 1 FROM accounting_counterpartydeletion WHERE entity_id=party) THEN
  RAISE EXCEPTION 'Visible same-office identity required' USING ERRCODE='23514',CONSTRAINT='cr007_entity';
 END IF;
 IF mode='PURGE' THEN
  IF role_name<>'owner' OR NOT person.is_archived OR person.name<>('Διαγραμμένη εγγραφή #'||party::text)
    OR accounting_cr005_financial_history(party) OR EXISTS(SELECT 1 FROM accounting_clienttask WHERE entity_id=party AND status='OPEN') THEN
   RAISE EXCEPTION 'Only approved owner deletion may remove fiscal data' USING ERRCODE='23514',CONSTRAINT='cr007_purge';
  END IF;
 ELSIF person.is_archived THEN
  RAISE EXCEPTION 'Restore archived identity before changing or revealing fiscal data' USING ERRCODE='23514',CONSTRAINT='cr007_archived';
 END IF;
 RETURN actor;
END $$;

CREATE FUNCTION accounting_cr007_tags(value jsonb) RETURNS boolean LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE item jsonb; label text; labels text[]:='{}';
BEGIN
 IF jsonb_typeof(value)<>'array' OR jsonb_array_length(value)>25 THEN RETURN false; END IF;
 FOR item IN SELECT * FROM jsonb_array_elements(value) LOOP
  IF jsonb_typeof(item)<>'string' THEN RETURN false; END IF;
  label:=item#>>'{}';
  IF char_length(label) NOT BETWEEN 1 AND 40 OR label<>btrim(label) OR label ~ '[[:cntrl:]]' OR replace(lower(label),'ς','σ')=ANY(labels) THEN RETURN false; END IF;
  labels:=array_append(labels,replace(lower(label),'ς','σ'));
 END LOOP;
 RETURN true;
END $$;

CREATE FUNCTION accounting_cr007_profile_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE mode text; person accounting_entity;
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Fiscal identity is retained' USING ERRCODE='23514',CONSTRAINT='cr007_profile_retained'; END IF;
 PERFORM accounting_cr007_actor(NEW.office_id,NEW.entity_id);
 mode:=current_setting('accounting.cr007_action');
 SELECT * INTO person FROM accounting_entity WHERE id=NEW.entity_id AND office_id=NEW.office_id;
 IF TG_OP='UPDATE' AND (NEW.id,NEW.office_id,NEW.entity_id) IS DISTINCT FROM (OLD.id,OLD.office_id,OLD.entity_id) THEN
  RAISE EXCEPTION 'Fiscal identity is immutable' USING ERRCODE='23514',CONSTRAINT='cr007_profile_identity';
 END IF;
 IF mode NOT IN('EDIT','PURGE') OR NEW.record_version<>person.record_version
   OR (TG_OP='UPDATE' AND NEW.record_version<=OLD.record_version) THEN
  RAISE EXCEPTION 'Versioned fiscal edit required' USING ERRCODE='23514',CONSTRAINT='cr007_profile_version';
 END IF;
 IF NEW.main_amka<>'' AND NEW.main_amka !~ '^[0-9]{11}$'
  OR NEW.spouse_amka<>'' AND NEW.spouse_amka !~ '^[0-9]{11}$'
  OR NEW.spouse_vat_number<>'' AND NEW.spouse_vat_number !~ '^[0-9]{9}$'
  OR char_length(NEW.internal_notes)>10000 OR NOT accounting_cr007_tags(NEW.tags) THEN
  RAISE EXCEPTION 'Invalid fiscal syntax' USING ERRCODE='23514',CONSTRAINT='cr007_profile_syntax';
 END IF;
 IF mode='EDIT' AND (NEW.person_kind='UNREVIEWED'
   OR person.legal_kind<>CASE WHEN NEW.person_kind IN('SOLE_TRADER','LEGAL_ENTITY') THEN 'BUSINESS' ELSE 'INDIVIDUAL' END) THEN
  RAISE EXCEPTION 'Explicit compatible fiscal category required' USING ERRCODE='23514',CONSTRAINT='cr007_profile_kind';
 END IF;
 IF NEW.spouse_enabled AND (NEW.person_kind='LEGAL_ENTITY' OR NEW.spouse_first_name !~ '[^[:space:]]'
   OR NEW.spouse_last_name !~ '[^[:space:]]' OR NEW.spouse_person_kind='UNREVIEWED') THEN
  RAISE EXCEPTION 'Explicit spouse identity required' USING ERRCODE='23514',CONSTRAINT='cr007_spouse_identity';
 END IF;
 IF NOT NEW.spouse_enabled AND (NEW.spouse_first_name<>'' OR NEW.spouse_last_name<>'' OR NEW.spouse_vat_number<>''
  OR NEW.spouse_amka<>'' OR NEW.spouse_tax_office<>'' OR NEW.spouse_person_kind<>'UNREVIEWED' OR NOT NEW.spouse_inherit_contacts) THEN
  RAISE EXCEPTION 'Disabled spouse fields must be empty' USING ERRCODE='23514',CONSTRAINT='cr007_spouse_disabled';
 END IF;
 IF NEW.spouse_inherit_contacts AND (NEW.spouse_address<>'' OR NEW.spouse_city<>'' OR NEW.spouse_postal_code<>''
  OR NEW.spouse_phone_number<>'' OR NEW.spouse_email<>'') THEN
  RAISE EXCEPTION 'Inherited contacts are computed from the current primary identity' USING ERRCODE='23514',CONSTRAINT='cr007_spouse_contacts';
 END IF;
 IF mode='PURGE' AND (NEW.person_kind<>'UNREVIEWED' OR NEW.contact_status<>'INACTIVE'
  OR NEW.main_amka<>'' OR NEW.spouse_enabled OR NEW.internal_notes<>'' OR NEW.tags<>'[]'::jsonb
  OR NEW.liable_a21 OR NEW.prefilled_return OR NEW.disability OR NEW.rent_subsidy OR NEW.rented_home OR NEW.student_allowance) THEN
  RAISE EXCEPTION 'Deletion must clear all fiscal data' USING ERRCODE='23514',CONSTRAINT='cr007_purge';
 END IF;
 NEW.updated_at:=clock_timestamp(); RETURN NEW;
END $$;
CREATE TRIGGER cr007_profile_guard BEFORE INSERT OR UPDATE OR DELETE ON accounting_entityprofile
 FOR EACH ROW EXECUTE FUNCTION accounting_cr007_profile_guard();

CREATE FUNCTION accounting_cr007_credential_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE row_data accounting_taxiscredential; mode text;
BEGIN
 IF TG_OP='DELETE' THEN row_data:=OLD; ELSE row_data:=NEW; END IF;
 PERFORM accounting_cr007_actor(row_data.office_id,row_data.entity_id);
 mode:=current_setting('accounting.cr007_action');
 IF mode NOT IN('EDIT','PURGE') OR mode='PURGE' AND TG_OP<>'DELETE' THEN
  RAISE EXCEPTION 'Explicit credential update required' USING ERRCODE='23514',CONSTRAINT='cr007_credential_context';
 END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF;
 IF TG_OP='UPDATE' AND (NEW.id,NEW.office_id,NEW.entity_id,NEW.subject) IS DISTINCT FROM (OLD.id,OLD.office_id,OLD.entity_id,OLD.subject) THEN
  RAISE EXCEPTION 'Credential identity is immutable' USING ERRCODE='23514',CONSTRAINT='cr007_credential_identity';
 END IF;
 IF octet_length(NEW.salt)<>16 OR octet_length(NEW.sealed_username) NOT BETWEEN 100 AND 1000
  OR octet_length(NEW.sealed_password) NOT BETWEEN 100 AND 2000
  OR convert_from(NEW.sealed_username,'UTF8') !~ '^gAAAA[A-Za-z0-9_=-]+$'
  OR convert_from(NEW.sealed_password,'UTF8') !~ '^gAAAA[A-Za-z0-9_=-]+$' THEN
  RAISE EXCEPTION 'Only sealed credentials are stored' USING ERRCODE='23514',CONSTRAINT='cr007_credential_sealed';
 END IF;
 IF NEW.subject='SPOUSE' AND NOT EXISTS(SELECT 1 FROM accounting_entityprofile WHERE entity_id=NEW.entity_id
  AND office_id=NEW.office_id AND spouse_enabled) THEN
  RAISE EXCEPTION 'Spouse profile required' USING ERRCODE='23514',CONSTRAINT='cr007_credential_spouse';
 END IF;
 NEW.updated_at:=clock_timestamp(); RETURN NEW;
END $$;
CREATE TRIGGER cr007_credential_guard BEFORE INSERT OR UPDATE OR DELETE ON accounting_taxiscredential
 FOR EACH ROW EXECUTE FUNCTION accounting_cr007_credential_guard();

CREATE FUNCTION accounting_cr007_event_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE actor bigint; mode text; item jsonb;
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Fiscal audit is append only' USING ERRCODE='23514',CONSTRAINT='cr007_event_retained'; END IF;
 actor:=accounting_cr007_actor(NEW.office_id,NEW.entity_id); mode:=current_setting('accounting.cr007_action');
 IF NEW.actor_id<>actor OR NEW.record_version<>(SELECT record_version FROM accounting_entity WHERE id=NEW.entity_id)
  OR NEW.action NOT IN('UPDATE','REVEAL','VAULT_SET','VAULT_CLEAR','PURGE')
  OR (NEW.action='REVEAL' AND (mode<>'REVEAL' OR NEW.changed_fields NOT IN('["MAIN"]'::jsonb,'["SPOUSE"]'::jsonb)))
  OR (NEW.action<>'REVEAL' AND pg_trigger_depth()<2)
  OR jsonb_typeof(NEW.changed_fields)<>'array' THEN
  RAISE EXCEPTION 'Exact fiscal audit transition required' USING ERRCODE='23514',CONSTRAINT='cr007_event_context';
 END IF;
 FOR item IN SELECT * FROM jsonb_array_elements(NEW.changed_fields) LOOP
  IF jsonb_typeof(item)<>'string' OR (item#>>'{}') NOT IN('contact_status','person_kind','main_amka','spouse_enabled',
   'spouse_first_name','spouse_last_name','spouse_vat_number','spouse_tax_office','spouse_amka','spouse_person_kind',
   'spouse_inherit_contacts','spouse_address','spouse_city','spouse_postal_code','spouse_phone_number','spouse_email',
   'liable_a21','prefilled_return','disability','rent_subsidy','rented_home','student_allowance','tags','internal_notes','MAIN','SPOUSE') THEN
   RAISE EXCEPTION 'Only field names belong in audit' USING ERRCODE='23514',CONSTRAINT='cr007_event_fields';
  END IF;
 END LOOP;
 NEW.subject:=CASE WHEN NEW.changed_fields IN('["MAIN"]'::jsonb,'["SPOUSE"]'::jsonb) THEN NEW.changed_fields->>0 ELSE '' END;
 SELECT username INTO NEW.actor_label FROM auth_user WHERE id=actor;
 NEW.occurred_at:=clock_timestamp(); RETURN NEW;
END $$;
CREATE TRIGGER cr007_profile_event_guard BEFORE INSERT OR UPDATE OR DELETE ON accounting_entityprofileevent
 FOR EACH ROW EXECUTE FUNCTION accounting_cr007_event_guard();

CREATE FUNCTION accounting_cr007_generated_audit() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE row_data jsonb; prior jsonb; changed jsonb; action_name text; subject_name text;
BEGIN
 IF TG_OP='DELETE' THEN row_data:=to_jsonb(OLD); ELSE row_data:=to_jsonb(NEW); END IF;
 IF TG_TABLE_NAME='accounting_entityprofile' THEN
  IF TG_OP='INSERT' THEN prior:='{}'::jsonb; ELSE prior:=to_jsonb(OLD); END IF;
  SELECT coalesce(jsonb_agg(key ORDER BY key),'[]'::jsonb) INTO changed FROM jsonb_each(row_data)
   WHERE key NOT IN('id','office_id','entity_id','record_version','updated_at') AND value IS DISTINCT FROM prior->key;
  action_name:=CASE current_setting('accounting.cr007_action') WHEN 'PURGE' THEN 'PURGE' ELSE 'UPDATE' END;
 ELSE
  subject_name:=row_data->>'subject'; changed:=jsonb_build_array(subject_name);
  action_name:=CASE WHEN current_setting('accounting.cr007_action')='PURGE' THEN 'PURGE'
    WHEN TG_OP='DELETE' THEN 'VAULT_CLEAR' ELSE 'VAULT_SET' END;
 END IF;
 INSERT INTO accounting_entityprofileevent(id,office_id,entity_id,actor_id,actor_label,action,subject,changed_fields,record_version,occurred_at)
 VALUES(gen_random_uuid(),(row_data->>'office_id')::uuid,(row_data->>'entity_id')::bigint,
  current_setting('accounting.s18_actor')::bigint,'',action_name,'',changed,
  (SELECT record_version FROM accounting_entity WHERE id=(row_data->>'entity_id')::bigint),clock_timestamp());
 IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
END $$;
CREATE TRIGGER cr007_profile_audit AFTER INSERT OR UPDATE ON accounting_entityprofile
 FOR EACH ROW EXECUTE FUNCTION accounting_cr007_generated_audit();
CREATE TRIGGER cr007_credential_audit AFTER INSERT OR UPDATE OR DELETE ON accounting_taxiscredential
 FOR EACH ROW EXECUTE FUNCTION accounting_cr007_generated_audit();
"""

REVERSE = r"""
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM accounting_entityprofile) OR EXISTS(SELECT 1 FROM accounting_taxiscredential)
   OR EXISTS(SELECT 1 FROM accounting_entityprofileevent) THEN
  RAISE EXCEPTION 'Retain fiscal profiles, credentials and audit before a reviewed downgrade';
 END IF;
END $$;
DROP TRIGGER cr007_credential_audit ON accounting_taxiscredential;
DROP TRIGGER cr007_profile_audit ON accounting_entityprofile;
DROP FUNCTION accounting_cr007_generated_audit();
DROP TRIGGER cr007_profile_event_guard ON accounting_entityprofileevent;
DROP FUNCTION accounting_cr007_event_guard();
DROP TRIGGER cr007_credential_guard ON accounting_taxiscredential;
DROP FUNCTION accounting_cr007_credential_guard();
DROP TRIGGER cr007_profile_guard ON accounting_entityprofile;
DROP FUNCTION accounting_cr007_profile_guard();
DROP FUNCTION accounting_cr007_tags(jsonb);
DROP FUNCTION accounting_cr007_actor(uuid,bigint);
ALTER TABLE accounting_entityprofileevent DROP CONSTRAINT cr007_event_actor;
ALTER TABLE accounting_entityprofileevent DROP CONSTRAINT cr007_event_office;
ALTER TABLE accounting_taxiscredential DROP CONSTRAINT cr007_credential_office;
ALTER TABLE accounting_entityprofile DROP CONSTRAINT cr007_profile_office;
"""


class Migration(migrations.Migration):
    dependencies = [('accounting','0033_entity_fiscal_profile')]
    operations = [migrations.RunSQL(FORWARD,REVERSE)]
