"""Append-only, fresh-authority configuration guards; no ledger changes."""
from django.db import migrations

SQL = r'''
CREATE FUNCTION accounting_s27_configuration_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
 owner_required boolean := false;
 prev_revision integer;
 prev_date date;
 prev_cancelled boolean;
 plan accounting_feeschedule;
 terms accounting_agreementtermsversion;
 agreement_row accounting_agreement;
 today date := (clock_timestamp() AT TIME ZONE 'Europe/Athens')::date;
BEGIN
 IF TG_OP<>'INSERT' THEN
  RAISE EXCEPTION 'Configuration history is retained' USING ERRCODE='23514',CONSTRAINT='s27_retained';
 END IF;
 IF TG_TABLE_NAME IN ('accounting_serviceitem','accounting_serviceprice') THEN
  owner_required := true;
 ELSIF TG_TABLE_NAME='accounting_feescheduleversion' THEN
  owner_required := NEW.revision>1;
 END IF;
 IF NEW.actor_id::text IS DISTINCT FROM nullif(current_setting('accounting.s18_actor',true),'') OR
    NEW.reason IS DISTINCT FROM nullif(current_setting('accounting.s18_reason',true),'') OR length(trim(NEW.reason))<4 OR
    NOT EXISTS(SELECT 1 FROM accounting_accountantprofile p JOIN auth_user u ON u.id=p.user_id
      JOIN accounting_office o ON o.id=p.office_id WHERE p.user_id=NEW.actor_id AND p.office_id=NEW.office_id
      AND p.is_active AND u.is_active AND o.is_active AND p.role IN ('owner','accountant')
      AND (NOT owner_required OR p.role='owner')) THEN
  RAISE EXCEPTION 'Fresh office authority and attributable reason required' USING ERRCODE='23514',CONSTRAINT='s27_authority';
 END IF;
 IF TG_TABLE_NAME='accounting_serviceitem' THEN
  IF NEW.code !~ '^[A-Z0-9][A-Z0-9._-]{0,39}$' THEN
   RAISE EXCEPTION 'Invalid service code' USING ERRCODE='23514',CONSTRAINT='s27_code';
  END IF;
 ELSIF TG_TABLE_NAME='accounting_serviceprice' THEN
  PERFORM 1 FROM accounting_serviceitem WHERE id=NEW.service_id AND office_id=NEW.office_id FOR UPDATE;
  IF NOT FOUND THEN
   RAISE EXCEPTION 'Foreign service' USING ERRCODE='23514',CONSTRAINT='s27_service_office';
  END IF;
  SELECT revision,effective_date INTO prev_revision,prev_date FROM accounting_serviceprice
   WHERE service_id=NEW.service_id ORDER BY revision DESC LIMIT 1;
  IF NEW.revision<>coalesce(prev_revision,0)+1 OR NEW.effective_date<today OR
     (prev_date IS NOT NULL AND NEW.effective_date<prev_date) OR length(trim(NEW.description))=0 THEN
   RAISE EXCEPTION 'Invalid price version' USING ERRCODE='23514',CONSTRAINT='s27_price_order';
  END IF;
 ELSIF TG_TABLE_NAME='accounting_feeschedule' THEN
  SELECT * INTO agreement_row FROM accounting_agreement WHERE id=NEW.agreement_id AND office_id=NEW.office_id FOR UPDATE;
  IF NOT FOUND THEN
   RAISE EXCEPTION 'Foreign agreement' USING ERRCODE='23514',CONSTRAINT='s27_agreement_office';
  END IF;
  SELECT * INTO terms FROM accounting_agreementtermsversion WHERE agreement_id=NEW.agreement_id AND office_id=NEW.office_id
   AND effective_date<=greatest(NEW.start_period,agreement_row.start_date) ORDER BY revision DESC LIMIT 1;
  IF terms.id IS NULL OR terms.billing_mode<>'MONTHLY' OR terms.lifecycle<>'ACTIVE' OR agreement_row.status='CANCELLED' OR
     agreement_row.agreement_type<>'RECEIVABLE' OR extract(day FROM NEW.start_period)<>1 OR
     NEW.start_period<date_trunc('month',agreement_row.start_date)::date OR
     NOT EXISTS(SELECT 1 FROM accounting_entity WHERE id=agreement_row.entity_id AND office_id=NEW.office_id AND is_customer AND NOT is_archived) OR
     (NEW.start_period=date_trunc('month',agreement_row.start_date)::date AND extract(day FROM agreement_row.start_date)<>1 AND NEW.first_amount IS NULL) OR
     ((NEW.start_period<>date_trunc('month',agreement_row.start_date)::date OR extract(day FROM agreement_row.start_date)=1) AND NEW.first_amount IS NOT NULL) THEN
   RAISE EXCEPTION 'Invalid reviewed monthly plan' USING ERRCODE='23514',CONSTRAINT='s27_plan_contract';
  END IF;
 ELSE
  SELECT * INTO plan FROM accounting_feeschedule WHERE id=NEW.schedule_id AND office_id=NEW.office_id FOR UPDATE;
  IF NOT FOUND THEN
   RAISE EXCEPTION 'Foreign schedule' USING ERRCODE='23514',CONSTRAINT='s27_schedule_office';
  END IF;
  SELECT * INTO agreement_row FROM accounting_agreement WHERE id=plan.agreement_id;
  SELECT * INTO terms FROM accounting_agreementtermsversion WHERE id=NEW.terms_snapshot_id AND office_id=NEW.office_id AND agreement_id=plan.agreement_id;
  SELECT revision,effective_period,cancelled INTO prev_revision,prev_date,prev_cancelled
   FROM accounting_feescheduleversion WHERE schedule_id=NEW.schedule_id ORDER BY revision DESC LIMIT 1;
  IF terms.id IS NULL OR NEW.revision<>coalesce(prev_revision,0)+1 OR extract(day FROM NEW.effective_period)<>1 OR
     (NEW.end_period IS NOT NULL AND extract(day FROM NEW.end_period)<>1) OR
     (prev_revision IS NULL AND (NEW.effective_period<>plan.start_period OR NEW.cancelled OR NEW.actor_id<>plan.actor_id)) OR
     (prev_revision IS NOT NULL AND (prev_cancelled OR NEW.effective_period<=prev_date OR NEW.effective_period<=date_trunc('month',today)::date)) OR
     (NOT NEW.cancelled AND (terms.billing_mode<>'MONTHLY' OR terms.lifecycle<>'ACTIVE' OR agreement_row.status='CANCELLED' OR
       NOT EXISTS(SELECT 1 FROM accounting_entity WHERE id=agreement_row.entity_id AND office_id=NEW.office_id AND is_customer AND NOT is_archived))) OR
     (prev_revision IS NULL AND plan.first_amount IS NOT NULL AND NOT NEW.due_next_month AND NEW.due_day<extract(day FROM agreement_row.start_date)) THEN
   RAISE EXCEPTION 'Invalid prospective schedule version' USING ERRCODE='23514',CONSTRAINT='s27_plan_version';
  END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER s27_service_guard BEFORE INSERT OR UPDATE OR DELETE ON accounting_serviceitem
 FOR EACH ROW EXECUTE FUNCTION accounting_s27_configuration_guard();
CREATE TRIGGER s27_price_guard BEFORE INSERT OR UPDATE OR DELETE ON accounting_serviceprice
 FOR EACH ROW EXECUTE FUNCTION accounting_s27_configuration_guard();
CREATE TRIGGER s27_schedule_guard BEFORE INSERT OR UPDATE OR DELETE ON accounting_feeschedule
 FOR EACH ROW EXECUTE FUNCTION accounting_s27_configuration_guard();
CREATE TRIGGER s27_version_guard BEFORE INSERT OR UPDATE OR DELETE ON accounting_feescheduleversion
 FOR EACH ROW EXECUTE FUNCTION accounting_s27_configuration_guard();
'''

REVERSE = '''
DROP TRIGGER s27_version_guard ON accounting_feescheduleversion;
DROP TRIGGER s27_schedule_guard ON accounting_feeschedule;
DROP TRIGGER s27_price_guard ON accounting_serviceprice;
DROP TRIGGER s27_service_guard ON accounting_serviceitem;
DROP FUNCTION accounting_s27_configuration_guard();
'''


class Migration(migrations.Migration):
    dependencies = [('accounting','0023_fee_catalogue_schedules')]
    operations = [migrations.RunSQL(SQL, REVERSE)]
