"""Retained correction groups, dated dependencies, refunds and term cutoffs."""
import importlib
from django.db import migrations


def old_function(module, name, *, sql=False):
    source = importlib.import_module('accounting.migrations.' + module).FORWARD
    start = source.index('CREATE FUNCTION ' + name + '(')
    end = source.index('$$;', start) + 3 if sql else source.index('END $$;', start) + 7
    return source[start:end].replace('CREATE FUNCTION', 'CREATE OR REPLACE FUNCTION', 1)


OLD_CASH = old_function('0012_financial_database_guards', 'accounting_s18_cash_guard')
OLD_COMMAND = old_function('0012_financial_database_guards', 'accounting_s18_command_guard')
OLD_COMPLETE = old_function('0012_financial_database_guards', 'accounting_s18_complete_group')
OLD_SCOPE = old_function('0014_cash_workspace_guards', 'accounting_s19_cash_scope')
OLD_CHARGE = old_function('0016_agreement_charge_guards', 'accounting_s22_charge_guard')
OLD_ALLOCATE = old_function('0018_settlement_guards', 'accounting_s23_allocation_guard')
OLD_USED = old_function('0018_settlement_guards', 'accounting_s23_used_at', sql=True)
OLD_LINKS = importlib.import_module('accounting.migrations.0012_financial_database_guards').S18_LINK

FORWARD = r"""
ALTER TABLE accounting_charge ALTER COLUMN amount TYPE numeric;
ALTER TABLE accounting_cashrefund ALTER COLUMN amount TYPE numeric;
ALTER TABLE accounting_agreementchange ALTER COLUMN amount TYPE numeric;
ALTER TABLE accounting_allocationrelease ADD CONSTRAINT s24_release_id_office UNIQUE(id,office_id);
ALTER TABLE accounting_financecorrection ADD CONSTRAINT s24_correction_actor_office FOREIGN KEY(actor_id,office_id) REFERENCES accounting_accountantprofile(user_id,office_id);
ALTER TABLE accounting_financecorrection ADD CONSTRAINT s24_correction_cash_office FOREIGN KEY(source_cash_id,office_id) REFERENCES accounting_transaction(id,office_id);
ALTER TABLE accounting_financecorrection ADD CONSTRAINT s24_correction_charge_office FOREIGN KEY(source_charge_id,office_id) REFERENCES accounting_charge(id,office_id);
ALTER TABLE accounting_financecorrection ADD CONSTRAINT s24_correction_agreement_office FOREIGN KEY(agreement_id,office_id) REFERENCES accounting_agreement(id,office_id);
ALTER TABLE accounting_financecorrection ADD CONSTRAINT s24_correction_command_office FOREIGN KEY(cash_command_id,office_id) REFERENCES accounting_financecommand(id,office_id);
ALTER TABLE accounting_correctionrelease ADD CONSTRAINT s24_release_action_office FOREIGN KEY(correction_id,office_id) REFERENCES accounting_financecorrection(id,office_id);
ALTER TABLE accounting_correctionrelease ADD CONSTRAINT s24_release_event_office FOREIGN KEY(release_id,office_id) REFERENCES accounting_allocationrelease(id,office_id);
ALTER TABLE accounting_cashrefund ADD CONSTRAINT s24_refund_action_office FOREIGN KEY(correction_id,office_id) REFERENCES accounting_financecorrection(id,office_id);
ALTER TABLE accounting_cashrefund ADD CONSTRAINT s24_refund_source_office FOREIGN KEY(source_cash_id,office_id) REFERENCES accounting_transaction(id,office_id);
ALTER TABLE accounting_cashrefund ADD CONSTRAINT s24_refund_entry_office FOREIGN KEY(entry_id,office_id) REFERENCES accounting_transaction(id,office_id);
ALTER TABLE accounting_chargereversal ADD CONSTRAINT s24_charge_reverse_action FOREIGN KEY(correction_id,office_id) REFERENCES accounting_financecorrection(id,office_id);
ALTER TABLE accounting_chargereversal ADD CONSTRAINT s24_charge_reverse_source FOREIGN KEY(charge_id,office_id) REFERENCES accounting_charge(id,office_id);
ALTER TABLE accounting_chargereplacement ADD CONSTRAINT s24_replace_action_office FOREIGN KEY(correction_id,office_id) REFERENCES accounting_financecorrection(id,office_id);
ALTER TABLE accounting_chargereplacement ADD CONSTRAINT s24_replace_original_office FOREIGN KEY(original_id,office_id) REFERENCES accounting_charge(id,office_id);
ALTER TABLE accounting_chargereplacement ADD CONSTRAINT s24_replace_new_office FOREIGN KEY(replacement_id,office_id) REFERENCES accounting_charge(id,office_id);
ALTER TABLE accounting_agreementchange ADD CONSTRAINT s24_terms_action_office FOREIGN KEY(correction_id,office_id) REFERENCES accounting_financecorrection(id,office_id);
ALTER TABLE accounting_agreementchange ADD CONSTRAINT s24_terms_agreement_office FOREIGN KEY(agreement_id,office_id) REFERENCES accounting_agreement(id,office_id);
ALTER TABLE accounting_agreementchange ADD CONSTRAINT s24_terms_version_office FOREIGN KEY(version_id,office_id,agreement_id) REFERENCES accounting_agreementtermsversion(id,office_id,agreement_id);
ALTER TABLE accounting_financeperiodclose ADD CONSTRAINT s24_period_action_office FOREIGN KEY(correction_id,office_id) REFERENCES accounting_financecorrection(id,office_id);

CREATE FUNCTION accounting_s24_open_date(off uuid, business_day date) RETURNS void LANGUAGE plpgsql VOLATILE AS $$
BEGIN
 IF business_day<=(SELECT max(closed_through) FROM accounting_financeperiodclose WHERE office_id=off) THEN
   RAISE EXCEPTION 'Date belongs to a declared closed period' USING ERRCODE='23514',CONSTRAINT='s24_period_closed';
 END IF;
END $$;

CREATE FUNCTION accounting_s24_action(off uuid) RETURNS accounting_financecorrection LANGUAGE plpgsql AS $$
DECLARE result accounting_financecorrection;
BEGIN
 SELECT * INTO result FROM accounting_financecorrection WHERE id=nullif(current_setting('accounting.s24_correction',true),'')::uuid AND office_id=off FOR UPDATE;
 IF result.id IS NULL OR result.state<>'pending' OR result.actor_id::text IS DISTINCT FROM nullif(current_setting('accounting.s18_actor',true),'') THEN
   RAISE EXCEPTION 'Pending correction context required' USING ERRCODE='23514',CONSTRAINT='s24_action_context';
 END IF;
 RETURN result;
END $$;

CREATE FUNCTION accounting_s24_action_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE expected integer; source accounting_transaction;
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Correction group is retained' USING ERRCODE='23514',CONSTRAINT='s24_action_immutable'; END IF;
 PERFORM accounting_s19_touch(NEW.office_id);
 IF NEW.operation NOT IN ('CASH','TRANSFER','CHARGE','REFUND','REFUND_REVERSE','TERMS','CLOSE') OR
    NEW.key_digest !~ '^sha256:[0-9a-f]{64}$' OR NEW.payload_digest !~ '^sha256:[0-9a-f]{64}$' OR
    length(trim(NEW.reason))<4 OR length(NEW.reason)>500 OR
    NEW.actor_id::text IS DISTINCT FROM nullif(current_setting('accounting.s18_actor',true),'') OR
    NOT EXISTS(SELECT 1 FROM accounting_accountantprofile p JOIN auth_user u ON u.id=p.user_id JOIN accounting_office o ON o.id=p.office_id
       WHERE p.user_id=NEW.actor_id AND p.office_id=NEW.office_id AND p.role='owner' AND p.is_active AND u.is_active AND o.is_active) THEN
   RAISE EXCEPTION 'Attributable owner correction required' USING ERRCODE='23514',CONSTRAINT='s24_action_actor';
 END IF;
 IF (NEW.operation IN ('CASH','TRANSFER','REFUND','REFUND_REVERSE')) IS DISTINCT FROM (NEW.source_cash_id IS NOT NULL) OR
    (NEW.operation='CHARGE') IS DISTINCT FROM (NEW.source_charge_id IS NOT NULL) OR
    (NEW.operation='TERMS') IS DISTINCT FROM (NEW.agreement_id IS NOT NULL) OR
    NEW.expected_release_count>1000 OR NEW.refund_reversal_count>100 OR
    (NEW.operation NOT IN ('CASH','CHARGE') AND NEW.expected_release_count<>0) OR
    (NEW.operation<>'CASH' AND NEW.refund_reversal_count<>0) OR
    (NEW.has_replacement AND NEW.operation NOT IN ('CASH','TRANSFER','CHARGE')) THEN
   RAISE EXCEPTION 'Correction source or expected member shape differs' USING ERRCODE='23514',CONSTRAINT='s24_action_shape';
 END IF;
 expected:=CASE NEW.operation WHEN 'CASH' THEN 1+NEW.has_replacement::int+NEW.refund_reversal_count
   WHEN 'TRANSFER' THEN 2+2*NEW.has_replacement::int WHEN 'REFUND' THEN 1 WHEN 'REFUND_REVERSE' THEN 1 ELSE 0 END;
 IF NEW.expected_cash_count<>expected OR (NEW.operation<>'TERMS' AND NEW.effective_date>(clock_timestamp() AT TIME ZONE 'Europe/Athens')::date) THEN
   RAISE EXCEPTION 'Invalid correction date or size' USING ERRCODE='23514',CONSTRAINT='s24_action_shape';
 END IF;
 -- A close group's own retained cutoff exists before its completion update.
 -- Check new work here; immutable identity prevents a date change on completion.
 IF TG_OP='INSERT' THEN PERFORM accounting_s24_open_date(NEW.office_id,NEW.effective_date); END IF;
 IF NEW.source_cash_id IS NOT NULL THEN
   SELECT * INTO source FROM accounting_transaction WHERE id=NEW.source_cash_id AND office_id=NEW.office_id FOR UPDATE;
   IF source.id IS NULL OR NEW.effective_date<source.transaction_date OR
     (NEW.operation='CASH' AND source.posting_kind NOT IN ('ORDINARY','LEGACY')) OR
     (NEW.operation='TRANSFER' AND source.posting_kind<>'TRANSFER') OR
     (NEW.operation='REFUND' AND source.posting_kind<>'ORDINARY') OR
     (NEW.operation='REFUND_REVERSE' AND source.posting_kind<>'REFUND') THEN
     RAISE EXCEPTION 'Correction needs its eligible retained source' USING ERRCODE='23514',CONSTRAINT='s24_action_source';
   END IF;
 END IF;
 IF TG_OP='INSERT' THEN
   IF NEW.state<>'pending' OR NEW.cash_command_id IS NOT NULL OR NEW.completed_at IS NOT NULL THEN
     RAISE EXCEPTION 'Correction must start pending without cash members' USING ERRCODE='23514',CONSTRAINT='s24_action_state';
   END IF;
   NEW.recorded_at:=clock_timestamp();
 ELSIF OLD.state='pending' AND NEW.state='pending' AND OLD.cash_command_id IS NULL AND NEW.cash_command_id IS NOT NULL AND pg_trigger_depth()>1 AND
       (to_jsonb(OLD)-'cash_command_id')=(to_jsonb(NEW)-'cash_command_id') THEN
   NULL; -- Bound only by the database's finance-command insertion trigger.
 ELSE
   IF OLD.state<>'pending' OR NEW.state<>'completed' OR
      (to_jsonb(OLD)-'state'-'completed_at') IS DISTINCT FROM (to_jsonb(NEW)-'state'-'completed_at') THEN
     RAISE EXCEPTION 'Correction identity is immutable' USING ERRCODE='23514',CONSTRAINT='s24_action_immutable';
   END IF;
   NEW.completed_at:=clock_timestamp();
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER s24_action_guard BEFORE INSERT OR UPDATE OR DELETE ON accounting_financecorrection FOR EACH ROW EXECUTE FUNCTION accounting_s24_action_guard();

CREATE FUNCTION accounting_s24_command_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE action accounting_financecorrection; expected text;
BEGIN
 IF NEW.operation IN ('transfer.reverse','transfer.correct','cash.refund','refund.reverse') OR nullif(current_setting('accounting.s24_correction',true),'') IS NOT NULL THEN
   action:=accounting_s24_action(NEW.office_id);
   expected:=CASE action.operation WHEN 'CASH' THEN CASE WHEN action.has_replacement THEN 'cash.correct' ELSE 'cash.reverse' END
     WHEN 'TRANSFER' THEN CASE WHEN action.has_replacement THEN 'transfer.correct' ELSE 'transfer.reverse' END
     WHEN 'REFUND' THEN 'cash.refund' WHEN 'REFUND_REVERSE' THEN 'refund.reverse' ELSE '' END;
   IF NEW.operation<>expected OR NEW.actor_id<>action.actor_id OR NEW.reason<>action.reason OR
      (TG_OP='INSERT' AND action.cash_command_id IS NOT NULL) OR (TG_OP='UPDATE' AND action.cash_command_id IS DISTINCT FROM NEW.id) THEN
     RAISE EXCEPTION 'Cash command differs from its correction group' USING ERRCODE='23514',CONSTRAINT='s24_command_group';
   END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER s24_command_guard BEFORE INSERT OR UPDATE ON accounting_financecommand FOR EACH ROW EXECUTE FUNCTION accounting_s24_command_guard();

CREATE FUNCTION accounting_s24_bind_command() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE action accounting_financecorrection;
BEGIN
 IF nullif(current_setting('accounting.s24_correction',true),'') IS NOT NULL THEN
   action:=accounting_s24_action(NEW.office_id);
   UPDATE accounting_financecorrection SET cash_command_id=NEW.id WHERE id=action.id;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER s24_bind_command AFTER INSERT ON accounting_financecommand FOR EACH ROW EXECUTE FUNCTION accounting_s24_bind_command();

CREATE OR REPLACE FUNCTION accounting_s23_used_at(kind text, target text, business_day date) RETURNS numeric LANGUAGE sql VOLATILE AS $$
 SELECT coalesce((SELECT sum(a.amount) FROM accounting_cashallocation a
   WHERE (CASE WHEN kind='cash' THEN a.source_cash_id::text=target ELSE a.charge_id::text=target END) AND a.effective_date<=business_day
     AND NOT EXISTS(SELECT 1 FROM accounting_allocationrelease r WHERE r.allocation_id=a.id AND r.effective_date<=business_day)),0)
 + CASE WHEN kind='cash' THEN coalesce((SELECT sum(r.amount) FROM accounting_cashrefund r WHERE r.source_cash_id::text=target AND r.effective_date<=business_day
     AND NOT EXISTS(SELECT 1 FROM accounting_transaction t WHERE t.reversal_of_id=r.entry_id AND t.transaction_date<=business_day)),0) ELSE 0 END;
$$;

CREATE FUNCTION accounting_s24_cash_dates(target bigint, after_day date) RETURNS SETOF date LANGUAGE sql VOLATILE AS $$
 SELECT after_day UNION SELECT effective_date FROM accounting_cashallocation WHERE source_cash_id=target AND effective_date>=after_day UNION
 SELECT r.effective_date FROM accounting_allocationrelease r JOIN accounting_cashallocation a ON a.id=r.allocation_id WHERE a.source_cash_id=target AND r.effective_date>=after_day UNION
 SELECT effective_date FROM accounting_cashrefund WHERE source_cash_id=target AND effective_date>=after_day UNION
 SELECT t.transaction_date FROM accounting_transaction t JOIN accounting_cashrefund r ON r.entry_id=t.reversal_of_id WHERE r.source_cash_id=target AND t.transaction_date>=after_day;
$$;

CREATE FUNCTION accounting_s24_event_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE action accounting_financecorrection; source accounting_transaction; cash accounting_transaction; original accounting_charge;
 replacement accounting_charge; released accounting_allocationrelease; allocated accounting_cashallocation;
 previous accounting_agreementtermsversion; agreement accounting_agreement; d date;
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Correction event is append only' USING ERRCODE='23514',CONSTRAINT='s24_event_immutable'; END IF;
 PERFORM accounting_s19_touch(NEW.office_id);
 action:=accounting_s24_action(NEW.office_id);
 IF action.id<>NEW.correction_id THEN RAISE EXCEPTION 'Event belongs to another correction' USING ERRCODE='23514',CONSTRAINT='s24_event_scope'; END IF;
 IF TG_TABLE_NAME='accounting_correctionrelease' THEN
   SELECT * INTO released FROM accounting_allocationrelease WHERE id=NEW.release_id AND office_id=NEW.office_id;
   SELECT * INTO allocated FROM accounting_cashallocation WHERE id=released.allocation_id AND office_id=NEW.office_id;
   IF released.id IS NULL OR released.recorded_at<action.recorded_at OR released.effective_date<>action.effective_date OR
      NOT EXISTS(SELECT 1 FROM accounting_settlementcommand WHERE id=released.command_id AND actor_id=action.actor_id AND state='completed') OR
      NOT ((action.operation='CASH' AND allocated.source_cash_id=action.source_cash_id) OR (action.operation='CHARGE' AND allocated.charge_id=action.source_charge_id)) THEN
     RAISE EXCEPTION 'Correction release differs from its original target' USING ERRCODE='23514',CONSTRAINT='s24_release_scope';
   END IF;
 ELSIF TG_TABLE_NAME='accounting_cashrefund' THEN
   SELECT * INTO source FROM accounting_transaction WHERE id=NEW.source_cash_id AND office_id=NEW.office_id FOR UPDATE;
   SELECT * INTO cash FROM accounting_transaction WHERE id=NEW.entry_id AND office_id=NEW.office_id;
   IF action.operation<>'REFUND' OR action.source_cash_id<>NEW.source_cash_id OR source.posting_kind<>'ORDINARY' OR source.entity_id IS NULL OR
      EXISTS(SELECT 1 FROM accounting_transaction WHERE reversal_of_id=source.id) OR cash.id IS NULL OR cash.command_id IS DISTINCT FROM action.cash_command_id OR
      cash.posting_kind<>'REFUND' OR (cash.amount,cash.transaction_date,cash.entity_id,cash.agreement_id,cash.category_id) IS DISTINCT FROM
      (NEW.amount,NEW.effective_date,source.entity_id,source.agreement_id,source.category_id) OR cash.transaction_type=source.transaction_type OR
      NEW.effective_date<>action.effective_date OR NEW.amount<=0 OR NEW.amount>9999999999.99 OR NEW.amount<>round(NEW.amount,2) THEN
     RAISE EXCEPTION 'Refund must consume an explicit eligible source' USING ERRCODE='23514',CONSTRAINT='s24_refund_source';
   END IF;
   FOR d IN SELECT * FROM accounting_s24_cash_dates(source.id,NEW.effective_date) LOOP
     IF accounting_s23_used_at('cash',source.id::text,d)+NEW.amount>source.amount THEN
       RAISE EXCEPTION 'Refund exceeds dated source availability' USING ERRCODE='23514',CONSTRAINT='s24_refund_capacity';
     END IF;
   END LOOP;
   NEW.recorded_at:=clock_timestamp();
 ELSIF TG_TABLE_NAME='accounting_chargereversal' THEN
   SELECT * INTO original FROM accounting_charge WHERE id=NEW.charge_id AND office_id=NEW.office_id FOR UPDATE;
   IF action.operation<>'CHARGE' OR action.source_charge_id<>NEW.charge_id OR original.id IS NULL OR NEW.effective_date<>action.effective_date OR NEW.effective_date<original.effective_date OR
      EXISTS(SELECT 1 FROM accounting_cashallocation a WHERE a.charge_id=original.id AND
        (a.effective_date>NEW.effective_date OR NOT EXISTS(SELECT 1 FROM accounting_allocationrelease r WHERE r.allocation_id=a.id AND r.effective_date<=NEW.effective_date))) THEN
     RAISE EXCEPTION 'Release charge allocations before a full dated reversal' USING ERRCODE='23514',CONSTRAINT='s24_charge_reversal';
   END IF;
   NEW.recorded_at:=clock_timestamp();
 ELSIF TG_TABLE_NAME='accounting_chargereplacement' THEN
   SELECT * INTO original FROM accounting_charge WHERE id=NEW.original_id AND office_id=NEW.office_id;
   SELECT * INTO replacement FROM accounting_charge WHERE id=NEW.replacement_id AND office_id=NEW.office_id;
   IF action.operation<>'CHARGE' OR NOT action.has_replacement OR NEW.original_id<>action.source_charge_id OR original.id IS NULL OR replacement.id IS NULL OR
      replacement.source_key<>'correction:'||action.id::text OR NOT EXISTS(SELECT 1 FROM accounting_chargereversal WHERE charge_id=original.id AND correction_id=action.id) THEN
     RAISE EXCEPTION 'Replacement must reference the same reversed charge' USING ERRCODE='23514',CONSTRAINT='s24_charge_replacement';
   END IF;
 ELSIF TG_TABLE_NAME='accounting_agreementchange' THEN
   SELECT * INTO agreement FROM accounting_agreement WHERE id=NEW.agreement_id AND office_id=NEW.office_id FOR UPDATE;
   SELECT * INTO previous FROM accounting_agreementtermsversion WHERE agreement_id=agreement.id AND office_id=NEW.office_id ORDER BY revision DESC LIMIT 1;
   IF action.operation<>'TERMS' OR action.agreement_id<>NEW.agreement_id OR previous.id IS NULL OR previous.revision<>NEW.previous_revision OR
      previous.billing_mode='UNREVIEWED' OR previous.lifecycle IN ('CANCELLED','ENDED') OR agreement.status='CANCELLED' OR
      NEW.billing_mode<>previous.billing_mode OR NEW.lifecycle NOT IN ('ACTIVE','CANCELLED','ENDED') OR
      action.effective_date<(clock_timestamp() AT TIME ZONE 'Europe/Athens')::date OR
      (NEW.lifecycle='ACTIVE' AND action.effective_date<previous.effective_date) OR
      length(trim(NEW.description))=0 OR NEW.amount<=0 OR NEW.amount>9999999999.99 OR NEW.amount<>round(NEW.amount,2) OR
      (NEW.lifecycle='ACTIVE' AND NOT EXISTS(SELECT 1 FROM accounting_entity WHERE id=agreement.entity_id AND office_id=NEW.office_id AND NOT is_archived AND
        CASE WHEN agreement.agreement_type='RECEIVABLE' THEN is_customer ELSE is_supplier END)) THEN
     RAISE EXCEPTION 'Prospective change needs current reviewed terms and cutoff' USING ERRCODE='23514',CONSTRAINT='s24_terms_change';
   END IF;
   INSERT INTO accounting_agreementtermsversion(office_id,agreement_id,entity_id,revision,billing_mode,lifecycle,direction,description,agreed_amount,start_date,effective_date,actor_id,origin,reason,recorded_at)
     VALUES(NEW.office_id,agreement.id,agreement.entity_id,previous.revision+1,NEW.billing_mode,NEW.lifecycle,agreement.agreement_type,NEW.description,NEW.amount,agreement.start_date,action.effective_date,action.actor_id,'user',action.reason,clock_timestamp()) RETURNING id INTO NEW.version_id;
 ELSIF TG_TABLE_NAME='accounting_financeperiodclose' THEN
   IF action.operation<>'CLOSE' OR NEW.closed_through<>action.effective_date OR NEW.closed_through<=(SELECT max(closed_through) FROM accounting_financeperiodclose WHERE office_id=NEW.office_id) THEN
     RAISE EXCEPTION 'Period cutoff must advance once' USING ERRCODE='23514',CONSTRAINT='s24_period_order';
   END IF;
   NEW.recorded_at:=clock_timestamp();
 END IF;
 RETURN NEW;
END $$;
"""

FORWARD += r"""
CREATE FUNCTION accounting_s24_cash_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE action accounting_financecorrection; cmd accounting_financecommand; original accounting_transaction;
BEGIN
 PERFORM accounting_s24_open_date(NEW.office_id,NEW.transaction_date);
 IF NEW.posting_kind='REFUND' OR (NEW.posting_kind='REVERSAL' AND EXISTS(SELECT 1 FROM accounting_transaction WHERE id=NEW.reversal_of_id AND posting_kind IN ('TRANSFER','REFUND'))) OR
    (NEW.posting_kind='TRANSFER' AND EXISTS(SELECT 1 FROM accounting_financecommand WHERE id=NEW.command_id AND operation='transfer.correct')) THEN
   action:=accounting_s24_action(NEW.office_id);
   SELECT * INTO cmd FROM accounting_financecommand WHERE id=NEW.command_id AND office_id=NEW.office_id FOR UPDATE;
   IF cmd.id IS NULL OR cmd.state<>'pending' OR cmd.actor_id<>action.actor_id OR cmd.id IS DISTINCT FROM action.cash_command_id OR
      NEW.transaction_type NOT IN ('INCOME','EXPENSE') OR NEW.transaction_date<>action.effective_date THEN
     RAISE EXCEPTION 'Extended cash entry needs its pending correction' USING ERRCODE='23514',CONSTRAINT='s24_cash_group';
   END IF;
   IF NEW.posting_kind='REVERSAL' THEN
     SELECT * INTO original FROM accounting_transaction WHERE id=NEW.reversal_of_id AND office_id=NEW.office_id FOR UPDATE;
     IF original.id IS NULL OR NEW.amount<>original.amount OR NEW.transaction_type=original.transaction_type OR NEW.transaction_date<original.transaction_date OR
       (NEW.cash_account_id,NEW.entity_id,NEW.agreement_id,NEW.category_id) IS DISTINCT FROM (original.cash_account_id,original.entity_id,original.agreement_id,original.category_id) OR
       (original.posting_kind='TRANSFER' AND (action.operation<>'TRANSFER' OR original.transfer_id<>(SELECT transfer_id FROM accounting_transaction WHERE id=action.source_cash_id))) OR
       (original.posting_kind='REFUND' AND NOT ((action.operation='REFUND_REVERSE' AND action.source_cash_id=original.id) OR
           (action.operation='CASH' AND EXISTS(SELECT 1 FROM accounting_cashrefund WHERE entry_id=original.id AND source_cash_id=action.source_cash_id)))) THEN
       RAISE EXCEPTION 'Correction must exactly negate its retained source' USING ERRCODE='23514',CONSTRAINT='s24_cash_original';
     END IF;
   ELSE
     IF NOT EXISTS(SELECT 1 FROM accounting_cashaccount WHERE id=NEW.cash_account_id AND office_id=NEW.office_id AND is_active) THEN
       RAISE EXCEPTION 'New cash needs an active account' USING ERRCODE='23514',CONSTRAINT='s24_cash_account';
     END IF;
     IF NEW.posting_kind='REFUND' AND action.operation<>'REFUND' THEN
       RAISE EXCEPTION 'Refund needs explicit source confirmation' USING ERRCODE='23514',CONSTRAINT='s24_refund_context';
     END IF;
     IF NEW.posting_kind='TRANSFER' AND (action.operation<>'TRANSFER' OR NOT action.has_replacement OR NEW.entity_id IS NOT NULL OR NEW.agreement_id IS NOT NULL OR NEW.category_id IS NOT NULL) THEN
       RAISE EXCEPTION 'Replacement transfer has no settlement targets' USING ERRCODE='23514',CONSTRAINT='s24_transfer_targets';
     END IF;
   END IF;
 END IF;
 IF NEW.posting_kind='REVERSAL' AND EXISTS(SELECT 1 FROM accounting_cashrefund r WHERE r.source_cash_id=NEW.reversal_of_id AND
       (r.effective_date>NEW.transaction_date OR NOT EXISTS(SELECT 1 FROM accounting_transaction t WHERE t.reversal_of_id=r.entry_id AND t.transaction_date<=NEW.transaction_date))) THEN
   RAISE EXCEPTION 'Reverse dependent refunds before the source' USING ERRCODE='23514',CONSTRAINT='s24_refund_dependency';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER s24_cash_guard BEFORE INSERT ON accounting_transaction FOR EACH ROW EXECUTE FUNCTION accounting_s24_cash_guard();

CREATE FUNCTION accounting_s24_replacement_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE action accounting_financecorrection; original accounting_charge;
BEGIN
 PERFORM accounting_s24_open_date(NEW.office_id,NEW.effective_date);
 IF NEW.source_key LIKE 'correction:%' THEN
   action:=accounting_s24_action(NEW.office_id);
   SELECT * INTO original FROM accounting_charge WHERE id=action.source_charge_id AND office_id=NEW.office_id FOR UPDATE;
   IF action.operation<>'CHARGE' OR NOT action.has_replacement OR original.id IS NULL OR NEW.source_key<>'correction:'||action.id::text OR
      NOT EXISTS(SELECT 1 FROM accounting_chargereversal WHERE charge_id=original.id AND correction_id=action.id) OR
      (NEW.agreement_id,NEW.terms_id,NEW.entity_id,NEW.direction,NEW.currency,NEW.description) IS DISTINCT FROM
      (original.agreement_id,original.terms_id,original.entity_id,original.direction,original.currency,original.description) OR
      NEW.effective_date<>action.effective_date OR NEW.due_date<NEW.effective_date OR NEW.actor_id<>action.actor_id OR NEW.reason<>action.reason OR
      NEW.period IS DISTINCT FROM original.period OR NEW.amount<=0 OR NEW.amount>9999999999.99 OR NEW.amount<>round(NEW.amount,2) OR
      NEW.key_digest !~ '^sha256:[0-9a-f]{64}$' OR NEW.payload_digest !~ '^sha256:[0-9a-f]{64}$' OR
      NOT EXISTS(SELECT 1 FROM accounting_entity WHERE id=NEW.entity_id AND office_id=NEW.office_id AND NOT is_archived AND
        CASE WHEN NEW.direction='RECEIVABLE' THEN is_customer ELSE is_supplier END) THEN
     RAISE EXCEPTION 'Replacement charge differs from its explicit correction' USING ERRCODE='23514',CONSTRAINT='s24_replacement_source';
   END IF;
   NEW.recorded_at:=clock_timestamp();
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER s24_replacement_guard BEFORE INSERT ON accounting_charge FOR EACH ROW EXECUTE FUNCTION accounting_s24_replacement_guard();

CREATE FUNCTION accounting_s24_agreement_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF EXISTS(SELECT 1 FROM accounting_agreementchange WHERE agreement_id=OLD.id) AND
    (NEW.entity_id,NEW.agreement_type,NEW.total_amount,NEW.description,NEW.start_date,NEW.status) IS DISTINCT FROM
    (OLD.entity_id,OLD.agreement_type,OLD.total_amount,OLD.description,OLD.start_date,OLD.status) THEN
   RAISE EXCEPTION 'Versioned agreement uses prospective retained changes' USING ERRCODE='23514',CONSTRAINT='s24_agreement_history';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER s24_agreement_guard BEFORE UPDATE ON accounting_agreement FOR EACH ROW EXECUTE FUNCTION accounting_s24_agreement_guard();

CREATE FUNCTION accounting_s24_date_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE day date;
BEGIN
 IF TG_TABLE_NAME='accounting_cashaccount' THEN
   IF TG_OP='UPDATE' AND NEW.opening_date IS NOT DISTINCT FROM OLD.opening_date THEN RETURN NEW; END IF;
   day:=NEW.opening_date;
 ELSE day:=NEW.effective_date; END IF;
 IF day IS NOT NULL THEN PERFORM accounting_s24_open_date(NEW.office_id,day); END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER s24_date_guard BEFORE INSERT ON accounting_cashallocation FOR EACH ROW EXECUTE FUNCTION accounting_s24_date_guard();
CREATE TRIGGER s24_date_guard BEFORE INSERT ON accounting_allocationrelease FOR EACH ROW EXECUTE FUNCTION accounting_s24_date_guard();
CREATE TRIGGER s24_date_guard BEFORE INSERT ON accounting_settlementcommand FOR EACH ROW EXECUTE FUNCTION accounting_s24_date_guard();
CREATE TRIGGER s24_date_guard BEFORE INSERT ON accounting_cashadjustment FOR EACH ROW EXECUTE FUNCTION accounting_s24_date_guard();
CREATE TRIGGER s24_date_guard BEFORE INSERT OR UPDATE ON accounting_cashaccount FOR EACH ROW EXECUTE FUNCTION accounting_s24_date_guard();

CREATE FUNCTION accounting_s24_complete_action(key uuid) RETURNS void LANGUAGE plpgsql AS $$
DECLARE action accounting_financecorrection; cmd accounting_financecommand; n integer; reversals integer; ordinary integer; transfers integer; a accounting_transaction; b accounting_transaction;
BEGIN
 SELECT * INTO action FROM accounting_financecorrection WHERE id=key;
 IF action.id IS NULL OR action.state<>'completed' OR action.completed_at IS NULL OR
   (SELECT count(*) FROM accounting_correctionrelease WHERE correction_id=key)<>action.expected_release_count OR
   (SELECT count(*) FROM accounting_cashrefund WHERE correction_id=key)<>(action.operation='REFUND')::int OR
   (SELECT count(*) FROM accounting_chargereversal WHERE correction_id=key)<>(action.operation='CHARGE')::int OR
   (SELECT count(*) FROM accounting_chargereplacement WHERE correction_id=key)<>((action.operation='CHARGE') AND action.has_replacement)::int OR
   (SELECT count(*) FROM accounting_agreementchange WHERE correction_id=key)<>(action.operation='TERMS')::int OR
   (SELECT count(*) FROM accounting_financeperiodclose WHERE correction_id=key)<>(action.operation='CLOSE')::int THEN
   RAISE EXCEPTION 'Correction group must commit completely once' USING ERRCODE='23514',CONSTRAINT='s24_complete_group';
 END IF;
 IF action.expected_cash_count=0 THEN
   IF action.cash_command_id IS NOT NULL THEN RAISE EXCEPTION 'Noncash correction cannot contain cash' USING ERRCODE='23514',CONSTRAINT='s24_complete_group'; END IF;
   RETURN;
 END IF;
 SELECT * INTO cmd FROM accounting_financecommand WHERE id=action.cash_command_id AND office_id=action.office_id;
 SELECT count(*),count(*) FILTER(WHERE posting_kind='REVERSAL'),count(*) FILTER(WHERE posting_kind='ORDINARY'),count(*) FILTER(WHERE posting_kind='TRANSFER')
   INTO n,reversals,ordinary,transfers FROM accounting_transaction WHERE command_id=cmd.id;
 IF cmd.id IS NULL OR cmd.state<>'completed' OR cmd.completed_at IS NULL OR cmd.actor_id<>action.actor_id OR n<>action.expected_cash_count OR
   (SELECT count(*) FROM accounting_financeauditevent WHERE command_id=cmd.id AND entry_id IS NOT NULL)<>n OR
   EXISTS(SELECT 1 FROM accounting_transaction WHERE command_id=cmd.id AND transaction_date<>action.effective_date) THEN
   RAISE EXCEPTION 'Cash and audit correction members differ' USING ERRCODE='23514',CONSTRAINT='s24_complete_group';
 END IF;
 IF action.operation='CASH' THEN
   IF ordinary<>action.has_replacement::int OR reversals<>1+action.refund_reversal_count OR
      (SELECT count(*) FROM accounting_transaction WHERE command_id=cmd.id AND reversal_of_id=action.source_cash_id)<>1 OR
      (SELECT count(*) FROM accounting_transaction t JOIN accounting_cashrefund r ON r.entry_id=t.reversal_of_id WHERE t.command_id=cmd.id AND r.source_cash_id=action.source_cash_id)<>action.refund_reversal_count THEN
     RAISE EXCEPTION 'Cash correction dependencies differ' USING ERRCODE='23514',CONSTRAINT='s24_complete_group';
   END IF;
 ELSIF action.operation='TRANSFER' THEN
   IF reversals<>2 OR transfers<>2*action.has_replacement::int OR ordinary<>0 OR
      (SELECT count(*) FROM accounting_transaction t JOIN accounting_transaction o ON o.id=t.reversal_of_id
       WHERE t.command_id=cmd.id AND o.posting_kind='TRANSFER' AND o.transfer_id=(SELECT transfer_id FROM accounting_transaction WHERE id=action.source_cash_id))<>2 THEN
     RAISE EXCEPTION 'Transfer must reverse both original legs together' USING ERRCODE='23514',CONSTRAINT='s24_transfer_group';
   END IF;
   IF action.has_replacement THEN
     SELECT * INTO a FROM accounting_transaction WHERE command_id=cmd.id AND posting_kind='TRANSFER' ORDER BY id LIMIT 1;
     SELECT * INTO b FROM accounting_transaction WHERE command_id=cmd.id AND posting_kind='TRANSFER' ORDER BY id DESC LIMIT 1;
     IF a.cash_account_id=b.cash_account_id OR a.transfer_id<>b.transfer_id OR a.transaction_type=b.transaction_type OR a.amount<>b.amount OR a.transaction_date<>b.transaction_date THEN
       RAISE EXCEPTION 'Replacement transfer pair must balance' USING ERRCODE='23514',CONSTRAINT='s24_transfer_group';
     END IF;
   END IF;
 ELSIF action.operation='REFUND' THEN
   IF n<>1 OR NOT EXISTS(SELECT 1 FROM accounting_cashrefund r JOIN accounting_transaction t ON t.id=r.entry_id WHERE r.correction_id=action.id AND t.command_id=cmd.id AND t.posting_kind='REFUND') THEN
     RAISE EXCEPTION 'Refund must bind its one cash event' USING ERRCODE='23514',CONSTRAINT='s24_complete_group';
   END IF;
 ELSIF action.operation='REFUND_REVERSE' THEN
   IF reversals<>1 OR NOT EXISTS(SELECT 1 FROM accounting_transaction WHERE command_id=cmd.id AND reversal_of_id=action.source_cash_id) THEN
     RAISE EXCEPTION 'Refund correction must bind its original' USING ERRCODE='23514',CONSTRAINT='s24_complete_group';
   END IF;
 ELSE RAISE EXCEPTION 'Unexpected cash correction operation' USING ERRCODE='23514',CONSTRAINT='s24_complete_group';
 END IF;
END $$;

CREATE FUNCTION accounting_s24_complete_trigger() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_TABLE_NAME='accounting_financecorrection' THEN
   PERFORM accounting_s24_complete_action(NEW.id);
 ELSE
   PERFORM accounting_s24_complete_action(NEW.correction_id);
 END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER s24_complete_action AFTER INSERT OR UPDATE ON accounting_financecorrection DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION accounting_s24_complete_trigger();
"""

EVENT_TABLES = ('accounting_correctionrelease', 'accounting_cashrefund', 'accounting_chargereversal',
                'accounting_chargereplacement', 'accounting_agreementchange', 'accounting_financeperiodclose')
for table in EVENT_TABLES:
    FORWARD += f'CREATE TRIGGER s24_event_guard BEFORE INSERT OR UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION accounting_s24_event_guard();\n'
    FORWARD += f'CREATE CONSTRAINT TRIGGER s24_complete_event AFTER INSERT ON {table} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION accounting_s24_complete_trigger();\n'

# Keep old command/immutability paths intact. Extended members require S24's
# additional guard and completed-group proof, never a loose posting-kind flag.
NEW_CASH = OLD_CASH.replace('BEGIN\n', """BEGIN
 IF TG_OP='INSERT' AND (NEW.posting_kind='REFUND' OR (NEW.posting_kind='REVERSAL' AND EXISTS(SELECT 1 FROM accounting_transaction WHERE id=NEW.reversal_of_id AND posting_kind IN ('TRANSFER','REFUND'))) OR
   (NEW.posting_kind='TRANSFER' AND EXISTS(SELECT 1 FROM accounting_financecommand WHERE id=NEW.command_id AND operation='transfer.correct'))) THEN RETURN NEW; END IF;
""", 1)
NEW_COMMAND = OLD_COMMAND.replace("'cash.post','cash.transfer','cash.reverse','cash.correct'", "'cash.post','cash.transfer','cash.reverse','cash.correct','transfer.reverse','transfer.correct','cash.refund','refund.reverse'")
NEW_COMPLETE = OLD_COMPLETE.replace('DECLARE cmd accounting_financecommand;', 'DECLARE correction_key uuid; cmd accounting_financecommand;').replace(
    ' IF cmd.id IS NULL THEN RETURN NULL; END IF;', ''' IF cmd.id IS NULL THEN RETURN NULL; END IF;
 SELECT id INTO correction_key FROM accounting_financecorrection WHERE cash_command_id=cmd.id;
 IF correction_key IS NOT NULL THEN PERFORM accounting_s24_complete_action(correction_key); RETURN NULL; END IF;
 IF cmd.operation NOT IN ('cash.post','cash.transfer','cash.reverse','cash.correct') THEN RAISE EXCEPTION 'Extended operation lacks its correction' USING ERRCODE='23514',CONSTRAINT='s24_complete_group'; END IF;''')
NEW_SCOPE = OLD_SCOPE.replace("NEW.posting_kind<>'REVERSAL'", "NEW.posting_kind NOT IN ('REVERSAL','REFUND')")
NEW_LINKS = OLD_LINKS.replace("NEW.posting_kind='REVERSAL'", "NEW.posting_kind IN ('REVERSAL','REFUND')")
NEW_CHARGE = OLD_CHARGE.replace('BEGIN\n', """BEGIN
 IF TG_OP='INSERT' AND NEW.amount<>round(NEW.amount,2) THEN
   RAISE EXCEPTION 'Charge requires exact cents' USING ERRCODE='23514',CONSTRAINT='s24_charge_cents';
 END IF;
 IF TG_OP='INSERT' AND NEW.source_key LIKE 'correction:%' AND nullif(current_setting('accounting.s24_correction',true),'') IS NOT NULL THEN RETURN NEW; END IF;
""", 1).replace(
    'terms.revision<>(SELECT max(revision) FROM accounting_agreementtermsversion WHERE agreement_id=NEW.agreement_id)',
    'terms.revision<>(SELECT revision FROM accounting_agreementtermsversion WHERE agreement_id=NEW.agreement_id AND effective_date<=NEW.effective_date ORDER BY revision DESC LIMIT 1)').replace(
    '(terms.entity_id,terms.direction,terms.description,terms.agreed_amount,terms.start_date) IS DISTINCT FROM\n    (agreement.entity_id,agreement.agreement_type,agreement.description,agreement.total_amount,agreement.start_date)',
    '(terms.entity_id,terms.direction,terms.start_date) IS DISTINCT FROM (agreement.entity_id,agreement.agreement_type,agreement.start_date)')
NEW_ALLOCATE = OLD_ALLOCATE.replace("source.posting_kind<>'ORDINARY' OR source.entity_id", "source.posting_kind<>'ORDINARY' OR EXISTS(SELECT 1 FROM accounting_chargereversal WHERE charge_id=obligation.id) OR source.entity_id").replace(
    'SELECT NEW.effective_date UNION', 'SELECT * FROM accounting_s24_cash_dates(source.id,NEW.effective_date) UNION')
FORWARD += '\n'.join((NEW_CASH, NEW_COMMAND, NEW_COMPLETE, NEW_SCOPE, NEW_LINKS, NEW_CHARGE, NEW_ALLOCATE))

REVERSE = r"""
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM accounting_financecorrection) OR EXISTS(SELECT 1 FROM accounting_transaction WHERE posting_kind='REFUND') OR
    EXISTS(SELECT 1 FROM accounting_financecommand WHERE operation IN ('transfer.reverse','transfer.correct','cash.refund','refund.reverse')) THEN
   RAISE EXCEPTION 'Retain S24 correction and period history; unsafe downgrade denied' USING ERRCODE='23514';
 END IF;
END $$;
"""
REVERSE += '\n'.join((OLD_CASH, OLD_COMMAND, OLD_COMPLETE, OLD_SCOPE, OLD_LINKS, OLD_CHARGE, OLD_ALLOCATE, OLD_USED))
for table in EVENT_TABLES:
    REVERSE += f'DROP TRIGGER s24_complete_event ON {table};\nDROP TRIGGER s24_event_guard ON {table};\n'
REVERSE += r"""
DROP TRIGGER s24_complete_action ON accounting_financecorrection;
DROP FUNCTION accounting_s24_complete_trigger();
DROP FUNCTION accounting_s24_complete_action(uuid);
DROP TRIGGER s24_agreement_guard ON accounting_agreement;
DROP FUNCTION accounting_s24_agreement_guard();
DROP TRIGGER s24_date_guard ON accounting_cashaccount;
DROP TRIGGER s24_date_guard ON accounting_cashadjustment;
DROP TRIGGER s24_date_guard ON accounting_settlementcommand;
DROP TRIGGER s24_date_guard ON accounting_allocationrelease;
DROP TRIGGER s24_date_guard ON accounting_cashallocation;
DROP FUNCTION accounting_s24_date_guard();
DROP TRIGGER s24_replacement_guard ON accounting_charge;
DROP FUNCTION accounting_s24_replacement_guard();
DROP TRIGGER s24_cash_guard ON accounting_transaction;
DROP FUNCTION accounting_s24_cash_guard();
DROP TRIGGER s24_bind_command ON accounting_financecommand;
DROP FUNCTION accounting_s24_bind_command();
DROP TRIGGER s24_command_guard ON accounting_financecommand;
DROP FUNCTION accounting_s24_command_guard();
DROP TRIGGER s24_action_guard ON accounting_financecorrection;
DROP FUNCTION accounting_s24_action_guard();
DROP FUNCTION accounting_s24_event_guard();
DROP FUNCTION accounting_s24_cash_dates(bigint,date);
DROP FUNCTION accounting_s24_action(uuid);
DROP FUNCTION accounting_s24_open_date(uuid,date);
ALTER TABLE accounting_financeperiodclose DROP CONSTRAINT s24_period_action_office;
ALTER TABLE accounting_agreementchange DROP CONSTRAINT s24_terms_version_office;
ALTER TABLE accounting_agreementchange DROP CONSTRAINT s24_terms_agreement_office;
ALTER TABLE accounting_agreementchange DROP CONSTRAINT s24_terms_action_office;
ALTER TABLE accounting_chargereplacement DROP CONSTRAINT s24_replace_new_office;
ALTER TABLE accounting_chargereplacement DROP CONSTRAINT s24_replace_original_office;
ALTER TABLE accounting_chargereplacement DROP CONSTRAINT s24_replace_action_office;
ALTER TABLE accounting_chargereversal DROP CONSTRAINT s24_charge_reverse_source;
ALTER TABLE accounting_chargereversal DROP CONSTRAINT s24_charge_reverse_action;
ALTER TABLE accounting_cashrefund DROP CONSTRAINT s24_refund_entry_office;
ALTER TABLE accounting_cashrefund DROP CONSTRAINT s24_refund_source_office;
ALTER TABLE accounting_cashrefund DROP CONSTRAINT s24_refund_action_office;
ALTER TABLE accounting_correctionrelease DROP CONSTRAINT s24_release_event_office;
ALTER TABLE accounting_correctionrelease DROP CONSTRAINT s24_release_action_office;
ALTER TABLE accounting_financecorrection DROP CONSTRAINT s24_correction_command_office;
ALTER TABLE accounting_financecorrection DROP CONSTRAINT s24_correction_agreement_office;
ALTER TABLE accounting_financecorrection DROP CONSTRAINT s24_correction_charge_office;
ALTER TABLE accounting_financecorrection DROP CONSTRAINT s24_correction_cash_office;
ALTER TABLE accounting_financecorrection DROP CONSTRAINT s24_correction_actor_office;
ALTER TABLE accounting_allocationrelease DROP CONSTRAINT s24_release_id_office;
ALTER TABLE accounting_charge ALTER COLUMN amount TYPE numeric(12,2);
ALTER TABLE accounting_cashrefund ALTER COLUMN amount TYPE numeric(12,2);
ALTER TABLE accounting_agreementchange ALTER COLUMN amount TYPE numeric(12,2);
"""


class Migration(migrations.Migration):
    dependencies = [('accounting', '0019_financial_corrections')]
    operations = [migrations.RunSQL(FORWARD, REVERSE)]
