"""S28 extends only the registered DB adapter; original probe rules are retained."""
from django.db import migrations

SQL = r'''
CREATE OR REPLACE FUNCTION accounting_s26_job_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='DELETE' THEN
  RAISE EXCEPTION 'Job history is retained' USING ERRCODE='23514',CONSTRAINT='s26_job_retained';
 END IF;
 IF NEW.kind='fee-occurrence.v1' THEN
  IF jsonb_typeof(NEW.payload)<>'object' OR
     NEW.payload-'schedule'-'period'-'automation'-'reason'<>'{}'::jsonb OR
     NOT (NEW.payload ?& ARRAY['schedule','period','automation','reason']) OR
     jsonb_typeof(NEW.payload->'schedule')<>'string' OR
     (NEW.payload->>'schedule') !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' OR
     jsonb_typeof(NEW.payload->'period')<>'string' OR
     (NEW.payload->>'period') !~ '^[0-9]{4}-(0[1-9]|1[0-2])$' OR
     NOT (NEW.payload->'automation'='null'::jsonb OR
       (jsonb_typeof(NEW.payload->'automation')='number' AND (NEW.payload->>'automation') ~ '^[1-9][0-9]*$')) OR
     jsonb_typeof(NEW.payload->'reason')<>'string' OR length(trim(NEW.payload->>'reason')) NOT BETWEEN 4 AND 500 OR
     NEW.payload_digest !~ '^sha256:[0-9a-f]{64}$' THEN
   RAISE EXCEPTION 'Invalid fee job payload' USING ERRCODE='23514',CONSTRAINT='s28_job_contract';
  END IF;
  IF NOT EXISTS(SELECT 1 FROM accounting_feeschedule s JOIN accounting_agreement a ON a.id=s.agreement_id
     WHERE s.id=(NEW.payload->>'schedule')::uuid AND s.office_id=NEW.office_id AND a.office_id=NEW.office_id
       AND a.entity_id=NEW.entity_id AND a.agreement_type='RECEIVABLE') THEN
   RAISE EXCEPTION 'Invalid fee job scope' USING ERRCODE='23514',CONSTRAINT='s28_job_scope';
  END IF;
 ELSIF NEW.kind<>'client-probe.v1' OR NEW.payload_digest !~ '^sha256:[0-9a-f]{64}$' OR
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
 IF NEW.state='succeeded' AND (
    (NEW.kind='client-probe.v1' AND NOT EXISTS(SELECT 1 FROM accounting_jobprobeeffect WHERE job_id=NEW.id)) OR
    (NEW.kind='fee-occurrence.v1' AND NOT EXISTS(SELECT 1 FROM accounting_feegenerationrun WHERE job_id=NEW.id AND outcome<>'pending'))) THEN
  RAISE EXCEPTION 'Success requires its committed effect' USING ERRCODE='23514',CONSTRAINT='s26_success_effect';
 END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION accounting_s28_automation_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE plan accounting_feeschedule; prior integer;
 today date := (clock_timestamp() AT TIME ZONE 'Europe/Athens')::date;
BEGIN
 IF TG_OP<>'INSERT' THEN
  RAISE EXCEPTION 'Automation history retained' USING ERRCODE='23514',CONSTRAINT='s28_policy_retained';
 END IF;
 PERFORM 1 FROM accounting_office WHERE id=NEW.office_id FOR UPDATE;
 SELECT * INTO plan FROM accounting_feeschedule WHERE id=NEW.schedule_id AND office_id=NEW.office_id;
 IF NOT FOUND OR NEW.actor_id::text IS DISTINCT FROM nullif(current_setting('accounting.s18_actor',true),'') OR
    NEW.reason IS DISTINCT FROM nullif(current_setting('accounting.s18_reason',true),'') OR length(trim(NEW.reason))<4 OR
    NOT EXISTS(SELECT 1 FROM accounting_accountantprofile p JOIN auth_user u ON u.id=p.user_id JOIN accounting_office o ON o.id=p.office_id
     WHERE p.user_id=NEW.actor_id AND p.office_id=NEW.office_id AND p.role='owner' AND p.is_active AND u.is_active AND o.is_active) THEN
  RAISE EXCEPTION 'Fresh attributable owner required' USING ERRCODE='23514',CONSTRAINT='s28_policy_authority';
 END IF;
 SELECT max(revision) INTO prior FROM accounting_feeautomationversion WHERE schedule_id=NEW.schedule_id;
 IF NEW.revision<>coalesce(prior,0)+1 OR NEW.first_period<>greatest(plan.start_period,date_trunc('month',today)::date) THEN
  RAISE EXCEPTION 'Invalid automation revision or catchup boundary' USING ERRCODE='23514',CONSTRAINT='s28_policy_version';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER s28_automation_guard BEFORE INSERT OR UPDATE OR DELETE ON accounting_feeautomationversion
 FOR EACH ROW EXECUTE FUNCTION accounting_s28_automation_guard();

CREATE FUNCTION accounting_s28_run_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE j accounting_backgroundjob; plan accounting_feeschedule; policy accounting_feeautomationversion;
BEGIN
 IF TG_OP='DELETE' THEN
  RAISE EXCEPTION 'Generation history retained' USING ERRCODE='23514',CONSTRAINT='s28_run_retained';
 END IF;
 SELECT * INTO j FROM accounting_backgroundjob WHERE id=NEW.job_id FOR UPDATE;
 SELECT * INTO plan FROM accounting_feeschedule WHERE id=NEW.schedule_id AND office_id=NEW.office_id;
 IF j.id IS NULL OR j.office_id<>NEW.office_id OR plan.id IS NULL OR j.kind<>'fee-occurrence.v1' OR
    (j.payload->>'schedule') IS DISTINCT FROM NEW.schedule_id::text OR
    (j.payload->>'period') IS DISTINCT FROM to_char(NEW.period,'YYYY-MM') OR extract(day FROM NEW.period)<>1 OR
    j.payload->'automation' IS DISTINCT FROM coalesce(to_jsonb(NEW.automation_id),'null'::jsonb) OR
    NEW.source_key IS DISTINCT FROM 'agreement:'||plan.agreement_id::text||':month:'||to_char(NEW.period,'YYYY-MM') THEN
  RAISE EXCEPTION 'Fee intent must match job and canonical source' USING ERRCODE='23514',CONSTRAINT='s28_run_scope';
 END IF;
 IF NEW.automation_id IS NOT NULL THEN
  SELECT * INTO policy FROM accounting_feeautomationversion WHERE id=NEW.automation_id AND office_id=NEW.office_id AND schedule_id=NEW.schedule_id;
  IF policy.id IS NULL OR policy.actor_id<>j.actor_id OR NEW.period<policy.first_period THEN
   RAISE EXCEPTION 'Invalid automation binding' USING ERRCODE='23514',CONSTRAINT='s28_run_policy';
  END IF;
 END IF;
 IF TG_OP='INSERT' THEN
  IF j.state<>'queued' OR NEW.outcome<>'pending' OR NEW.charge_id IS NOT NULL THEN
   RAISE EXCEPTION 'New fee intent must be pending' USING ERRCODE='23514',CONSTRAINT='s28_run_initial';
  END IF;
 ELSE
  IF (to_jsonb(NEW)-'outcome'-'charge_id') IS DISTINCT FROM (to_jsonb(OLD)-'outcome'-'charge_id') OR
     OLD.outcome<>'pending' OR NEW.outcome='pending' OR j.state<>'running' OR j.lease_until<=clock_timestamp() OR
     j.id::text IS DISTINCT FROM nullif(current_setting('accounting.s26_job',true),'') OR
     j.lease_token::text IS DISTINCT FROM nullif(current_setting('accounting.s26_lease',true),'') THEN
   RAISE EXCEPTION 'Current lease and immutable identity required' USING ERRCODE='23514',CONSTRAINT='s28_run_fence';
  END IF;
  IF NEW.outcome IN ('generated','existing') AND NOT EXISTS(SELECT 1 FROM accounting_charge c
    WHERE c.id=NEW.charge_id AND c.office_id=NEW.office_id AND c.agreement_id=plan.agreement_id AND c.period=NEW.period AND c.source_key=NEW.source_key) THEN
   RAISE EXCEPTION 'Receipt must reference the exact source charge' USING ERRCODE='23514',CONSTRAINT='s28_run_charge';
  END IF;
  IF NEW.outcome='generated' AND NEW.automation_id IS NOT NULL AND (
     NOT policy.enabled OR EXISTS(SELECT 1 FROM accounting_feeautomationversion p WHERE p.schedule_id=plan.id AND p.revision>policy.revision) OR
     NOT EXISTS(SELECT 1 FROM accounting_accountantprofile p WHERE p.user_id=j.actor_id AND p.office_id=j.office_id AND p.role='owner' AND p.is_active)) THEN
   RAISE EXCEPTION 'Automatic authority changed' USING ERRCODE='23514',CONSTRAINT='s28_run_authority';
  END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER s28_run_guard BEFORE INSERT OR UPDATE OR DELETE ON accounting_feegenerationrun
 FOR EACH ROW EXECUTE FUNCTION accounting_s28_run_guard();

'''

REVERSE = r'''
DROP TRIGGER s28_run_guard ON accounting_feegenerationrun;
DROP FUNCTION accounting_s28_run_guard();
DROP TRIGGER s28_automation_guard ON accounting_feeautomationversion;
DROP FUNCTION accounting_s28_automation_guard();
CREATE OR REPLACE FUNCTION accounting_s26_job_guard() RETURNS trigger LANGUAGE plpgsql AS $$
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
'''

class Migration(migrations.Migration):
    dependencies = [('accounting','0025_fee_generation')]
    operations = [migrations.RunSQL(SQL,REVERSE)]
