"""Retained identities, same-office links and a fenced atomic probe effect."""
from django.db import migrations

SQL = r'''
ALTER TABLE accounting_backgroundjob ADD CONSTRAINT s26_job_entity_office
 FOREIGN KEY(entity_id,office_id) REFERENCES accounting_entity(id,office_id);
ALTER TABLE accounting_backgroundjob ADD CONSTRAINT s26_job_actor_office
 FOREIGN KEY(actor_id,office_id) REFERENCES accounting_accountantprofile(user_id,office_id);
ALTER TABLE accounting_jobevent ADD CONSTRAINT s26_event_job_office
 FOREIGN KEY(job_id,office_id) REFERENCES accounting_backgroundjob(id,office_id);
ALTER TABLE accounting_jobprobeeffect ADD CONSTRAINT s26_effect_context
 FOREIGN KEY(job_id,office_id,entity_id,actor_id) REFERENCES accounting_backgroundjob(id,office_id,entity_id,actor_id);

CREATE FUNCTION accounting_s26_job_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='DELETE' THEN
  RAISE EXCEPTION 'Job history is retained' USING ERRCODE='23514',CONSTRAINT='s26_job_retained';
 END IF;
 IF NEW.kind<>'client-probe.v1' OR NEW.payload_digest !~ '^sha256:[0-9a-f]{64}$' OR
    jsonb_typeof(NEW.payload)<>'object' OR NEW.payload- 'failures'<>'{}'::jsonb OR
    NOT (NEW.payload ? 'failures') OR NEW.payload->'failures' NOT IN ('0'::jsonb,'1'::jsonb,'2'::jsonb) THEN
  RAISE EXCEPTION 'Unsupported job adapter or payload' USING ERRCODE='23514',CONSTRAINT='s26_job_contract';
 END IF;
 IF TG_OP='UPDATE' THEN
  IF (NEW.id,NEW.office_id,NEW.actor_id,NEW.entity_id,NEW.kind,NEW.key,NEW.correlation_id,NEW.payload,
      NEW.payload_digest,NEW.created_at,NEW.max_attempts) IS DISTINCT FROM
     (OLD.id,OLD.office_id,OLD.actor_id,OLD.entity_id,OLD.kind,OLD.key,OLD.correlation_id,OLD.payload,
      OLD.payload_digest,OLD.created_at,OLD.max_attempts) THEN
   RAISE EXCEPTION 'Job identity is immutable' USING ERRCODE='23514',CONSTRAINT='s26_job_identity';
  END IF;
  IF OLD.state IN ('succeeded','cancelled','blocked','failed') AND NEW IS DISTINCT FROM OLD THEN
   RAISE EXCEPTION 'Terminal receipt is retained' USING ERRCODE='23514',CONSTRAINT='s26_job_terminal';
  END IF;
  IF NEW.state<>OLD.state AND NOT (
     (OLD.state IN ('queued','retry') AND NEW.state IN ('running','cancelled','blocked','failed')) OR
     (OLD.state='running' AND NEW.state IN ('succeeded','retry','failed','cancelled','blocked'))) THEN
   RAISE EXCEPTION 'Invalid job transition' USING ERRCODE='23514',CONSTRAINT='s26_job_transition';
  END IF;
  IF NEW.attempts<>OLD.attempts + (CASE WHEN NEW.state='running' AND OLD.state<>'running' THEN 1 ELSE 0 END) THEN
   RAISE EXCEPTION 'Invalid attempt counter' USING ERRCODE='23514',CONSTRAINT='s26_attempt_counter';
  END IF;
 ELSE
  IF NEW.state<>'queued' OR NEW.attempts<>0 THEN
   RAISE EXCEPTION 'New job must be queued' USING ERRCODE='23514',CONSTRAINT='s26_job_initial';
  END IF;
 END IF;
 IF TG_OP='INSERT' OR NEW.state='running' THEN
  IF NOT EXISTS(SELECT 1 FROM accounting_accountantprofile p JOIN auth_user u ON u.id=p.user_id
     JOIN accounting_office o ON o.id=p.office_id JOIN accounting_entity e ON e.id=NEW.entity_id AND e.office_id=p.office_id
     WHERE p.user_id=NEW.actor_id AND p.office_id=NEW.office_id AND p.is_active AND u.is_active AND o.is_active
       AND p.role IN ('owner','accountant') AND NOT e.is_archived) THEN
   RAISE EXCEPTION 'Job authority revoked' USING ERRCODE='23514',CONSTRAINT='s26_job_authority';
  END IF;
 END IF;
 IF NEW.state='succeeded' AND NOT EXISTS(SELECT 1 FROM accounting_jobprobeeffect WHERE job_id=NEW.id) THEN
  RAISE EXCEPTION 'Success requires its committed effect' USING ERRCODE='23514',CONSTRAINT='s26_success_effect';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER s26_job_guard BEFORE INSERT OR UPDATE OR DELETE ON accounting_backgroundjob
 FOR EACH ROW EXECUTE FUNCTION accounting_s26_job_guard();

CREATE FUNCTION accounting_s26_event_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP<>'INSERT' THEN
  RAISE EXCEPTION 'Job event history is immutable' USING ERRCODE='23514',CONSTRAINT='s26_event_immutable';
 END IF;
 IF NEW.code NOT IN ('accepted','started','completed','broker_unavailable','worker_lost','transient_failure',
     'retry_exhausted','execution_failed','cancelled_by_actor','authority_revoked') OR
    NOT EXISTS(SELECT 1 FROM accounting_backgroundjob j WHERE j.id=NEW.job_id AND j.office_id=NEW.office_id
     AND j.state=NEW.state AND j.attempts=NEW.attempt) THEN
  RAISE EXCEPTION 'Event must match its job receipt' USING ERRCODE='23514',CONSTRAINT='s26_event_context';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER s26_event_guard BEFORE INSERT OR UPDATE OR DELETE ON accounting_jobevent
 FOR EACH ROW EXECUTE FUNCTION accounting_s26_event_guard();

CREATE FUNCTION accounting_s26_effect_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE j accounting_backgroundjob;
BEGIN
 IF TG_OP<>'INSERT' THEN
  RAISE EXCEPTION 'Probe effect is immutable' USING ERRCODE='23514',CONSTRAINT='s26_effect_immutable';
 END IF;
 SELECT * INTO j FROM accounting_backgroundjob WHERE id=NEW.job_id FOR UPDATE;
 IF j.state<>'running' OR j.lease_until<=clock_timestamp() OR
    j.id::text IS DISTINCT FROM nullif(current_setting('accounting.s26_job',true),'') OR
    j.lease_token::text IS DISTINCT FROM nullif(current_setting('accounting.s26_lease',true),'') OR
    NOT EXISTS(SELECT 1 FROM accounting_accountantprofile p JOIN auth_user u ON u.id=p.user_id
      JOIN accounting_office o ON o.id=p.office_id JOIN accounting_entity e ON e.id=NEW.entity_id AND e.office_id=p.office_id
      WHERE p.user_id=NEW.actor_id AND p.office_id=NEW.office_id AND p.is_active AND u.is_active AND o.is_active
       AND p.role IN ('owner','accountant') AND NOT e.is_archived) THEN
  RAISE EXCEPTION 'Current fenced authority required' USING ERRCODE='23514',CONSTRAINT='s26_effect_fence';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER s26_effect_guard BEFORE INSERT OR UPDATE OR DELETE ON accounting_jobprobeeffect
 FOR EACH ROW EXECUTE FUNCTION accounting_s26_effect_guard();
'''

REVERSE = '''
DROP TRIGGER s26_effect_guard ON accounting_jobprobeeffect;
DROP FUNCTION accounting_s26_effect_guard();
DROP TRIGGER s26_event_guard ON accounting_jobevent;
DROP FUNCTION accounting_s26_event_guard();
DROP TRIGGER s26_job_guard ON accounting_backgroundjob;
DROP FUNCTION accounting_s26_job_guard();
ALTER TABLE accounting_jobprobeeffect DROP CONSTRAINT s26_effect_context;
ALTER TABLE accounting_jobevent DROP CONSTRAINT s26_event_job_office;
ALTER TABLE accounting_backgroundjob DROP CONSTRAINT s26_job_actor_office;
ALTER TABLE accounting_backgroundjob DROP CONSTRAINT s26_job_entity_office;
'''


class Migration(migrations.Migration):
    dependencies = [('accounting', '0021_background_jobs')]
    operations = [migrations.RunSQL(SQL, REVERSE)]
