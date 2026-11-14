"""Retained snapshots, source uniqueness and same-office obligations on PG17."""
from django.db import migrations

FORWARD = """
ALTER TABLE accounting_agreementtermsversion ADD CONSTRAINT s22_terms_agreement_office
 FOREIGN KEY(agreement_id,office_id) REFERENCES accounting_agreement(id,office_id) DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE accounting_agreementtermsversion ADD CONSTRAINT s22_terms_entity_office
 FOREIGN KEY(entity_id,office_id) REFERENCES accounting_entity(id,office_id) DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE accounting_agreementtermsversion ADD CONSTRAINT s22_terms_actor_office
 FOREIGN KEY(actor_id,office_id) REFERENCES accounting_accountantprofile(user_id,office_id) DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE accounting_charge ADD CONSTRAINT s22_charge_agreement_office
 FOREIGN KEY(agreement_id,office_id) REFERENCES accounting_agreement(id,office_id) DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE accounting_charge ADD CONSTRAINT s22_charge_entity_office
 FOREIGN KEY(entity_id,office_id) REFERENCES accounting_entity(id,office_id) DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE accounting_charge ADD CONSTRAINT s22_charge_actor_office
 FOREIGN KEY(actor_id,office_id) REFERENCES accounting_accountantprofile(user_id,office_id) DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE accounting_charge ADD CONSTRAINT s22_charge_terms_office
 FOREIGN KEY(terms_id,office_id,agreement_id) REFERENCES accounting_agreementtermsversion(id,office_id,agreement_id) DEFERRABLE INITIALLY IMMEDIATE;

-- Reviewable baseline only. No charge, payment, lifecycle or paid flag is inferred.
INSERT INTO accounting_agreementtermsversion(office_id,agreement_id,entity_id,revision,billing_mode,lifecycle,
 direction,description,agreed_amount,start_date,effective_date,actor_id,origin,reason,recorded_at)
SELECT office_id,id,entity_id,0,'UNREVIEWED','UNREVIEWED',agreement_type,description,total_amount,start_date,
 start_date,NULL,'legacy','Απογραφή διατηρημένων όρων· απαιτείται επιλογή τρόπου χρέωσης',clock_timestamp()
FROM accounting_agreement;

CREATE FUNCTION accounting_s22_terms_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP<>'INSERT' OR pg_trigger_depth()<2 THEN
   RAISE EXCEPTION 'Agreement versions are trigger-written and append only' USING ERRCODE='23514',CONSTRAINT='s22_terms_immutable';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER s22_terms_immutable BEFORE INSERT OR UPDATE OR DELETE ON accounting_agreementtermsversion
 FOR EACH ROW EXECUTE FUNCTION accounting_s22_terms_immutable();

CREATE FUNCTION accounting_s22_agreement_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 PERFORM accounting_s19_touch(NEW.office_id);
 IF TG_OP='UPDATE' AND (NEW.entity_id,NEW.agreement_type,NEW.total_amount,NEW.description,NEW.start_date) IS DISTINCT FROM
    (OLD.entity_id,OLD.agreement_type,OLD.total_amount,OLD.description,OLD.start_date) AND
    EXISTS(SELECT 1 FROM accounting_charge WHERE agreement_id=OLD.id) THEN
   RAISE EXCEPTION 'Posted obligations retain their agreement terms; use prospective amendment' USING ERRCODE='23514',CONSTRAINT='s22_posted_terms';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER s22_agreement_guard BEFORE INSERT OR UPDATE ON accounting_agreement
 FOR EACH ROW EXECUTE FUNCTION accounting_s22_agreement_guard();

CREATE FUNCTION accounting_s22_terms_snapshot() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE previous accounting_agreementtermsversion; actor bigint; mode text; state text; why text; source text;
BEGIN
 SELECT * INTO previous FROM accounting_agreementtermsversion WHERE agreement_id=NEW.id ORDER BY revision DESC LIMIT 1;
 mode:=nullif(current_setting('accounting.s22_billing_mode',true),'');
 state:=nullif(current_setting('accounting.s22_lifecycle',true),'');
 -- S18's historical settlement projection may update status only. It is NOT
 -- contractual lifecycle and must neither create a charge nor mark one paid.
 IF TG_OP='UPDATE' AND (NEW.entity_id,NEW.agreement_type,NEW.total_amount,NEW.description,NEW.start_date) IS NOT DISTINCT FROM
    (OLD.entity_id,OLD.agreement_type,OLD.total_amount,OLD.description,OLD.start_date) AND
    (mode IS NULL OR (mode=previous.billing_mode AND state=previous.lifecycle)) THEN RETURN NEW;END IF;
 actor:=nullif(current_setting('accounting.s18_actor',true),'')::bigint;
 IF mode IS NULL OR mode='UNREVIEWED' THEN mode:='UNREVIEWED';state:='UNREVIEWED';END IF;
 IF mode NOT IN ('UNREVIEWED','ONE_OFF','MONTHLY') OR state IS NULL OR state NOT IN ('UNREVIEWED','DRAFT','ACTIVE','ENDED','CANCELLED') OR
    (mode='UNREVIEWED')<>(state='UNREVIEWED') THEN
   RAISE EXCEPTION 'Explicit valid billing/lifecycle choice required' USING ERRCODE='23514',CONSTRAINT='s22_terms_choice';
 END IF;
 IF mode<>'UNREVIEWED' AND actor IS NULL THEN
   RAISE EXCEPTION 'Reviewed terms require their accountant' USING ERRCODE='23514',CONSTRAINT='s22_terms_actor';
 END IF;
 IF mode<>'UNREVIEWED' AND (length(trim(NEW.description))=0 OR NEW.agreement_type NOT IN ('RECEIVABLE','PAYABLE') OR NOT EXISTS(
    SELECT 1 FROM accounting_entity WHERE id=NEW.entity_id AND office_id=NEW.office_id AND NOT is_archived AND
    CASE WHEN NEW.agreement_type='RECEIVABLE' THEN is_customer ELSE is_supplier END)) THEN
   RAISE EXCEPTION 'Reviewed terms need an active eligible counterparty' USING ERRCODE='23514',CONSTRAINT='s22_terms_role';
 END IF;
 IF actor IS NOT NULL AND NOT EXISTS(SELECT 1 FROM accounting_accountantprofile p JOIN auth_user u ON u.id=p.user_id
     JOIN accounting_office o ON o.id=p.office_id WHERE p.user_id=actor AND p.office_id=NEW.office_id AND p.is_active AND u.is_active AND o.is_active) THEN
   RAISE EXCEPTION 'Active same-office terms actor required' USING ERRCODE='23514',CONSTRAINT='s22_terms_actor';
 END IF;
 IF EXISTS(SELECT 1 FROM accounting_charge WHERE agreement_id=NEW.id) AND
    (mode,state) IS DISTINCT FROM (previous.billing_mode,previous.lifecycle) THEN
   RAISE EXCEPTION 'Posted agreement lifecycle changes require the correction workflow' USING ERRCODE='23514',CONSTRAINT='s22_posted_terms';
 END IF;
 source:=CASE WHEN actor IS NULL THEN 'database' ELSE 'user' END;
 why:=CASE WHEN actor IS NULL THEN 'Διαχειριστική απογραφή όρων σε αναμονή ελέγχου' ELSE nullif(current_setting('accounting.s18_reason',true),'') END;
 IF why IS NULL OR length(trim(why))<4 OR length(why)>500 THEN
   RAISE EXCEPTION 'Terms reason required' USING ERRCODE='23514',CONSTRAINT='s22_terms_reason';
 END IF;
 INSERT INTO accounting_agreementtermsversion(office_id,agreement_id,entity_id,revision,billing_mode,lifecycle,direction,
  description,agreed_amount,start_date,effective_date,actor_id,origin,reason,recorded_at)
 VALUES(NEW.office_id,NEW.id,NEW.entity_id,coalesce(previous.revision+1,CASE WHEN mode='UNREVIEWED' THEN 0 ELSE 1 END),mode,state,
  NEW.agreement_type,NEW.description,NEW.total_amount,NEW.start_date,NEW.start_date,actor,source,why,clock_timestamp());
 RETURN NEW;
END $$;
CREATE TRIGGER s22_terms_snapshot AFTER INSERT OR UPDATE ON accounting_agreement
 FOR EACH ROW EXECUTE FUNCTION accounting_s22_terms_snapshot();

CREATE FUNCTION accounting_s22_charge_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE terms accounting_agreementtermsversion; agreement accounting_agreement; expected_source text; first_month date;
BEGIN
 IF TG_OP<>'INSERT' THEN
   RAISE EXCEPTION 'Posted charge is immutable; use linked correction' USING ERRCODE='23514',CONSTRAINT='s22_charge_immutable';
 END IF;
 PERFORM accounting_s19_touch(NEW.office_id);
 SELECT * INTO agreement FROM accounting_agreement WHERE id=NEW.agreement_id AND office_id=NEW.office_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'Same office agreement required' USING ERRCODE='23514',CONSTRAINT='s22_charge_scope';END IF;
 SELECT * INTO terms FROM accounting_agreementtermsversion WHERE id=NEW.terms_id AND agreement_id=NEW.agreement_id AND office_id=NEW.office_id;
 IF NOT FOUND OR terms.billing_mode='UNREVIEWED' OR terms.lifecycle<>'ACTIVE' OR agreement.status='CANCELLED' OR
    terms.revision<>(SELECT max(revision) FROM accounting_agreementtermsversion WHERE agreement_id=NEW.agreement_id) OR
    (terms.entity_id,terms.direction,terms.description,terms.agreed_amount,terms.start_date) IS DISTINCT FROM
    (agreement.entity_id,agreement.agreement_type,agreement.description,agreement.total_amount,agreement.start_date) OR
    (NEW.entity_id,NEW.direction,NEW.description) IS DISTINCT FROM (terms.entity_id,terms.direction,terms.description) THEN
   RAISE EXCEPTION 'Current reviewed active terms required' USING ERRCODE='23514',CONSTRAINT='s22_charge_terms';
 END IF;
 IF NEW.actor_id::text IS DISTINCT FROM nullif(current_setting('accounting.s18_actor',true),'') OR
    nullif(current_setting('accounting.s18_command',true),'') IS NOT NULL OR
    NOT EXISTS(SELECT 1 FROM accounting_accountantprofile p JOIN auth_user u ON u.id=p.user_id JOIN accounting_office o ON o.id=p.office_id
      WHERE p.user_id=NEW.actor_id AND p.office_id=NEW.office_id AND p.is_active AND u.is_active AND o.is_active) THEN
   RAISE EXCEPTION 'Active same-office charge actor required' USING ERRCODE='23514',CONSTRAINT='s22_charge_actor';
 END IF;
 IF NEW.direction NOT IN ('RECEIVABLE','PAYABLE') OR NOT EXISTS(SELECT 1 FROM accounting_entity WHERE id=NEW.entity_id AND office_id=NEW.office_id AND NOT is_archived AND
    CASE WHEN NEW.direction='RECEIVABLE' THEN is_customer ELSE is_supplier END) THEN
   RAISE EXCEPTION 'Charge needs an active eligible counterparty' USING ERRCODE='23514',CONSTRAINT='s22_charge_role';
 END IF;
 IF NEW.effective_date<terms.effective_date OR NEW.effective_date>(clock_timestamp() AT TIME ZONE 'Europe/Athens')::date OR NEW.due_date<NEW.effective_date OR
    NEW.currency<>'EUR' OR NEW.amount<=0 OR NEW.amount>9999999999.99 OR NEW.key_digest !~ '^sha256:[0-9a-f]{64}$' OR
    NEW.payload_digest !~ '^sha256:[0-9a-f]{64}$' OR length(trim(NEW.reason))<4 OR length(NEW.reason)>500 THEN
   RAISE EXCEPTION 'Invalid charge dates money or posting metadata' USING ERRCODE='23514',CONSTRAINT='s22_charge_input';
 END IF;
 IF terms.billing_mode='ONE_OFF' THEN
   expected_source:='agreement:'||NEW.agreement_id||':one-off';
   IF NEW.period IS NOT NULL OR NEW.amount<>terms.agreed_amount THEN
     RAISE EXCEPTION 'One-off source is the entire reviewed obligation once' USING ERRCODE='23514',CONSTRAINT='s22_charge_occurrence';
   END IF;
 ELSE
   first_month:=date_trunc('month',terms.start_date)::date;
   IF NEW.period IS NULL OR NEW.period<>date_trunc('month',NEW.period)::date OR NEW.period<first_month OR
      NEW.period<>date_trunc('month',NEW.effective_date)::date OR
      (NEW.amount<>terms.agreed_amount AND NOT(NEW.period=first_month AND extract(day FROM terms.start_date)<>1)) THEN
     RAISE EXCEPTION 'Monthly source requires its calendar period and reviewed price' USING ERRCODE='23514',CONSTRAINT='s22_charge_occurrence';
   END IF;
   expected_source:='agreement:'||NEW.agreement_id||':month:'||to_char(NEW.period,'YYYY-MM');
 END IF;
 IF NEW.source_key<>expected_source THEN
   RAISE EXCEPTION 'A schedule or terms version cannot change the obligation source' USING ERRCODE='23514',CONSTRAINT='s22_charge_source_shape';
 END IF;
 NEW.recorded_at:=clock_timestamp();
 RETURN NEW;
END $$;
CREATE TRIGGER s22_charge_guard BEFORE INSERT OR UPDATE OR DELETE ON accounting_charge
 FOR EACH ROW EXECUTE FUNCTION accounting_s22_charge_guard();
"""

REVERSE = """
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM accounting_charge) OR EXISTS(SELECT 1 FROM accounting_agreementtermsversion WHERE origin='user' OR revision>0) THEN
   RAISE EXCEPTION 'Retain S22 reviewed terms and obligations; unsafe downgrade denied' USING ERRCODE='23514';
 END IF;
END $$;
DROP TRIGGER s22_charge_guard ON accounting_charge;
DROP FUNCTION accounting_s22_charge_guard();
DROP TRIGGER s22_terms_snapshot ON accounting_agreement;
DROP FUNCTION accounting_s22_terms_snapshot();
DROP TRIGGER s22_agreement_guard ON accounting_agreement;
DROP FUNCTION accounting_s22_agreement_guard();
DROP TRIGGER s22_terms_immutable ON accounting_agreementtermsversion;
DROP FUNCTION accounting_s22_terms_immutable();
ALTER TABLE accounting_charge DROP CONSTRAINT s22_charge_terms_office;
ALTER TABLE accounting_charge DROP CONSTRAINT s22_charge_actor_office;
ALTER TABLE accounting_charge DROP CONSTRAINT s22_charge_entity_office;
ALTER TABLE accounting_charge DROP CONSTRAINT s22_charge_agreement_office;
ALTER TABLE accounting_agreementtermsversion DROP CONSTRAINT s22_terms_actor_office;
ALTER TABLE accounting_agreementtermsversion DROP CONSTRAINT s22_terms_entity_office;
ALTER TABLE accounting_agreementtermsversion DROP CONSTRAINT s22_terms_agreement_office;
"""


class Migration(migrations.Migration):
    dependencies = [('accounting', '0015_agreement_charge_foundation')]
    operations = [migrations.RunSQL(FORWARD, REVERSE)]
