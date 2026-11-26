"""Finite dated budgets and immutable explicit cash/charge selection on PG17."""
import importlib
from django.db import migrations

previous=importlib.import_module('accounting.migrations.0020_financial_correction_guards')
OLD_SNAPSHOT=previous.old_function('0016_agreement_charge_guards','accounting_s22_terms_snapshot')
SNAPSHOT=OLD_SNAPSHOT.replace("('UNREVIEWED','ONE_OFF','MONTHLY')","('UNREVIEWED','ONE_OFF','MONTHLY','ON_DEMAND')")
OLD_CHARGE=previous.NEW_CHARGE
CHARGE=OLD_CHARGE.replace(" IF terms.billing_mode='ONE_OFF' THEN", """
 IF terms.billing_mode='ON_DEMAND' THEN
   IF NEW.period IS NOT NULL THEN
     RAISE EXCEPTION 'On-demand charges have no calendar period' USING ERRCODE='23514',CONSTRAINT='s22_charge_occurrence';
   END IF;
   expected_source:='agreement:'||NEW.agreement_id||':demand:'||substr(NEW.key_digest,8);
 ELSIF terms.billing_mode='ONE_OFF' THEN""")

FORWARD=SNAPSHOT+'\n'+CHARGE+r"""
CREATE FUNCTION accounting_cr012_budget_conflict(target bigint, anchor date,
 extra_amount numeric DEFAULT 0, excluded_charge uuid DEFAULT NULL, proposed_limit numeric DEFAULT NULL)
RETURNS TABLE(check_day date, charged numeric, agreed numeric) LANGUAGE sql VOLATILE AS $$
 WITH days AS (
   SELECT anchor AS day
   UNION SELECT effective_date FROM accounting_charge WHERE agreement_id=target AND effective_date>=anchor
   UNION SELECT r.effective_date FROM accounting_chargereversal r JOIN accounting_charge c ON c.id=r.charge_id
     WHERE c.agreement_id=target AND r.effective_date>=anchor
   UNION SELECT effective_date FROM accounting_agreementtermsversion WHERE agreement_id=target AND effective_date>=anchor
 ), states AS (
   SELECT d.day,t.billing_mode,coalesce(proposed_limit,t.agreed_amount) AS limit_amount,
     coalesce((SELECT sum(c.amount) FROM accounting_charge c WHERE c.agreement_id=target AND c.effective_date<=d.day
       AND NOT EXISTS(SELECT 1 FROM accounting_chargereversal r WHERE r.charge_id=c.id AND r.effective_date<=d.day)
       AND NOT(excluded_charge IS NOT NULL AND c.id=excluded_charge)),0)+extra_amount AS charged_amount
   FROM days d CROSS JOIN LATERAL (
     SELECT * FROM accounting_agreementtermsversion v WHERE v.agreement_id=target AND v.effective_date<=d.day
     ORDER BY v.revision DESC LIMIT 1
   ) t
 ) SELECT day,charged_amount,limit_amount FROM states
 WHERE billing_mode IN ('ONE_OFF','ON_DEMAND') AND charged_amount>limit_amount ORDER BY day LIMIT 1;
$$;

CREATE FUNCTION accounting_cr012_budget_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE bad record; approved numeric; mode text;
BEGIN
 PERFORM accounting_s19_touch(NEW.office_id);
 PERFORM 1 FROM accounting_agreement WHERE id=NEW.agreement_id AND office_id=NEW.office_id FOR UPDATE;
 SELECT * INTO bad FROM accounting_cr012_budget_conflict(NEW.agreement_id,NEW.effective_date);
 IF FOUND THEN
   RAISE EXCEPTION 'Posted charges exceed dated finite agreement budget' USING ERRCODE='23514',CONSTRAINT='cr012_budget_limit';
 END IF;
 IF TG_TABLE_NAME='accounting_charge' THEN
   SELECT billing_mode,agreed_amount INTO mode,approved FROM accounting_agreementtermsversion WHERE id=NEW.terms_id;
   IF mode='MONTHLY' AND NEW.amount>approved THEN
     RAISE EXCEPTION 'Charge exceeds the approved monthly period price' USING ERRCODE='23514',CONSTRAINT='cr012_monthly_limit';
   END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER cr012_charge_budget AFTER INSERT ON accounting_charge
 FOR EACH ROW EXECUTE FUNCTION accounting_cr012_budget_guard();
CREATE TRIGGER cr012_terms_budget AFTER INSERT ON accounting_agreementtermsversion
 FOR EACH ROW EXECUTE FUNCTION accounting_cr012_budget_guard();

CREATE FUNCTION accounting_cr012_receipt_capacity(target uuid, business_day date)
RETURNS numeric LANGUAGE sql VOLATILE AS $$
 SELECT greatest(0,c.amount-(SELECT max(accounting_s23_used_at('charge',c.id::text,points.day)) FROM (
   SELECT business_day AS day
   UNION SELECT effective_date FROM accounting_cashallocation WHERE charge_id=c.id AND effective_date>=business_day
   UNION SELECT r.effective_date FROM accounting_allocationrelease r JOIN accounting_cashallocation a ON a.id=r.allocation_id
     WHERE a.charge_id=c.id AND r.effective_date>=business_day
 ) points))
 FROM accounting_charge c WHERE c.id=target AND c.effective_date<=business_day
   AND NOT EXISTS(SELECT 1 FROM accounting_chargereversal r WHERE r.charge_id=c.id);
$$;

ALTER TABLE accounting_cashchargeselection ADD CONSTRAINT cr012_selection_cash_office
 FOREIGN KEY(source_cash_id,office_id) REFERENCES accounting_transaction(id,office_id);
ALTER TABLE accounting_cashchargeselection ADD CONSTRAINT cr012_selection_charge_office
 FOREIGN KEY(charge_id,office_id) REFERENCES accounting_charge(id,office_id);
ALTER TABLE accounting_cashchargeselection ADD CONSTRAINT cr012_selection_settlement_office
 FOREIGN KEY(settlement_id,office_id,source_cash_id) REFERENCES accounting_settlementcommand(id,office_id,source_cash_id);
ALTER TABLE accounting_cashchargeselection ADD CONSTRAINT cr012_selection_actor_office
 FOREIGN KEY(actor_id,office_id) REFERENCES accounting_accountantprofile(user_id,office_id);
ALTER TABLE accounting_cashchargeselection ALTER COLUMN allocated_amount TYPE numeric;

CREATE FUNCTION accounting_cr012_selection_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE cash accounting_transaction; obligation accounting_charge; cmd accounting_settlementcommand;
 owner_command accounting_financecommand; count_rows integer; allocated numeric;
BEGIN
 IF TG_OP<>'INSERT' THEN
   RAISE EXCEPTION 'Initial cash selection is append only' USING ERRCODE='23514',CONSTRAINT='cr012_selection_immutable';
 END IF;
 PERFORM accounting_s19_touch(NEW.office_id);
 SELECT * INTO cash FROM accounting_transaction WHERE id=NEW.source_cash_id AND office_id=NEW.office_id FOR UPDATE;
 SELECT * INTO obligation FROM accounting_charge WHERE id=NEW.charge_id AND office_id=NEW.office_id FOR UPDATE;
 SELECT * INTO cmd FROM accounting_settlementcommand WHERE id=NEW.settlement_id AND office_id=NEW.office_id;
 SELECT * INTO owner_command FROM accounting_financecommand WHERE id=cash.command_id AND office_id=NEW.office_id;
 IF cash.id IS NULL OR obligation.id IS NULL OR cmd.id IS NULL OR owner_command.id IS NULL OR
   cash.posting_kind<>'ORDINARY' OR cash.entity_id IS DISTINCT FROM obligation.entity_id OR cash.agreement_id IS DISTINCT FROM obligation.agreement_id OR
   obligation.direction<>(CASE WHEN cash.transaction_type='INCOME' THEN 'RECEIVABLE' ELSE 'PAYABLE' END) OR
   cash.transaction_type NOT IN ('INCOME','EXPENSE') OR cash.transaction_date<obligation.effective_date OR
   cmd.source_cash_id<>cash.id OR cmd.operation<>'ALLOCATE' OR cmd.state<>'completed' OR cmd.expected_count<>1 OR
   cmd.effective_date<>cash.transaction_date OR owner_command.operation<>'cash.post' OR owner_command.state<>'completed' OR
   (NEW.actor_id,cmd.actor_id) IS DISTINCT FROM (owner_command.actor_id,owner_command.actor_id) OR
   NEW.actor_id::text IS DISTINCT FROM nullif(current_setting('accounting.s18_actor',true),'') OR
   NOT EXISTS(SELECT 1 FROM accounting_accountantprofile p JOIN auth_user u ON u.id=p.user_id
     JOIN accounting_office o ON o.id=p.office_id WHERE p.user_id=NEW.actor_id AND p.office_id=NEW.office_id AND p.is_active AND u.is_active AND o.is_active) OR
   EXISTS(SELECT 1 FROM accounting_transaction WHERE reversal_of_id=cash.id) OR
   EXISTS(SELECT 1 FROM accounting_chargereversal WHERE charge_id=obligation.id) THEN
   RAISE EXCEPTION 'Initial selection requires same-party same-direction posted sources' USING ERRCODE='23514',CONSTRAINT='cr012_selection_scope';
 END IF;
 SELECT count(*),coalesce(sum(amount),0) INTO count_rows,allocated FROM accounting_cashallocation
   WHERE command_id=cmd.id AND office_id=NEW.office_id AND source_cash_id=cash.id AND charge_id=obligation.id;
 IF count_rows<>1 OR allocated<>NEW.allocated_amount OR NEW.allocated_amount<=0 OR NEW.allocated_amount>cash.amount OR
   NEW.allocated_amount<>round(NEW.allocated_amount,2) OR NEW.payload_sha256 !~ '^sha256:[0-9a-f]{64}$' OR
   EXISTS(SELECT 1 FROM accounting_cashallocation WHERE source_cash_id=cash.id AND command_id<>cmd.id) OR
   EXISTS(SELECT 1 FROM accounting_allocationrelease r JOIN accounting_cashallocation a ON a.id=r.allocation_id WHERE a.command_id=cmd.id) THEN
   RAISE EXCEPTION 'Initial selection needs its one completed immutable allocation' USING ERRCODE='23514',CONSTRAINT='cr012_selection_allocation';
 END IF;
 NEW.recorded_at:=clock_timestamp();RETURN NEW;
END $$;
CREATE TRIGGER cr012_selection_guard BEFORE INSERT OR UPDATE OR DELETE ON accounting_cashchargeselection
 FOR EACH ROW EXECUTE FUNCTION accounting_cr012_selection_guard();
"""

REVERSE=r"""
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM accounting_cashchargeselection) OR EXISTS(SELECT 1 FROM accounting_agreementtermsversion WHERE billing_mode='ON_DEMAND') THEN
   RAISE EXCEPTION 'Retain demand-charge and initial-selection history; downgrade denied' USING ERRCODE='23514';
 END IF;
END $$;
DROP TRIGGER cr012_selection_guard ON accounting_cashchargeselection;
DROP FUNCTION accounting_cr012_selection_guard();
ALTER TABLE accounting_cashchargeselection DROP CONSTRAINT cr012_selection_actor_office;
ALTER TABLE accounting_cashchargeselection DROP CONSTRAINT cr012_selection_settlement_office;
ALTER TABLE accounting_cashchargeselection DROP CONSTRAINT cr012_selection_charge_office;
ALTER TABLE accounting_cashchargeselection DROP CONSTRAINT cr012_selection_cash_office;
DROP TRIGGER cr012_terms_budget ON accounting_agreementtermsversion;
DROP TRIGGER cr012_charge_budget ON accounting_charge;
DROP FUNCTION accounting_cr012_budget_guard();
DROP FUNCTION accounting_cr012_receipt_capacity(uuid,date);
DROP FUNCTION accounting_cr012_budget_conflict(bigint,date,numeric,uuid,numeric);
"""+OLD_CHARGE+'\n'+OLD_SNAPSHOT


class Migration(migrations.Migration):
    dependencies=[('accounting','0041_demand_charges')]
    operations=[migrations.RunSQL(FORWARD,REVERSE)]
