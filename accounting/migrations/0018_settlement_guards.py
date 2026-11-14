"""Same-office, dated, bounded, append-only settlement commands on PostgreSQL."""
from django.db import migrations

FORWARD = r"""
ALTER TABLE accounting_cashallocation ALTER COLUMN amount TYPE numeric;
ALTER TABLE accounting_settlementcommand ADD CONSTRAINT s23_command_cash_office
 FOREIGN KEY(source_cash_id,office_id) REFERENCES accounting_transaction(id,office_id);
ALTER TABLE accounting_settlementcommand ADD CONSTRAINT s23_command_actor_office
 FOREIGN KEY(actor_id,office_id) REFERENCES accounting_accountantprofile(user_id,office_id);
ALTER TABLE accounting_cashallocation ADD CONSTRAINT s23_allocation_command_source
 FOREIGN KEY(command_id,office_id,source_cash_id) REFERENCES accounting_settlementcommand(id,office_id,source_cash_id);
ALTER TABLE accounting_cashallocation ADD CONSTRAINT s23_allocation_cash_office
 FOREIGN KEY(source_cash_id,office_id) REFERENCES accounting_transaction(id,office_id);
ALTER TABLE accounting_cashallocation ADD CONSTRAINT s23_allocation_charge_office
 FOREIGN KEY(charge_id,office_id) REFERENCES accounting_charge(id,office_id);
ALTER TABLE accounting_allocationrelease ADD CONSTRAINT s23_release_command_office
 FOREIGN KEY(command_id,office_id) REFERENCES accounting_settlementcommand(id,office_id);
ALTER TABLE accounting_allocationrelease ADD CONSTRAINT s23_release_allocation_office
 FOREIGN KEY(allocation_id,office_id) REFERENCES accounting_cashallocation(id,office_id);
CREATE INDEX s23_source_date ON accounting_cashallocation(source_cash_id,effective_date);
CREATE INDEX s23_charge_date ON accounting_cashallocation(charge_id,effective_date);

CREATE FUNCTION accounting_s23_used_at(kind text, target text, business_day date)
 RETURNS numeric LANGUAGE sql VOLATILE AS $$
 SELECT coalesce(sum(a.amount),0) FROM accounting_cashallocation a
 WHERE (CASE WHEN kind='cash' THEN a.source_cash_id::text=target ELSE a.charge_id::text=target END)
 AND a.effective_date<=business_day
 AND NOT EXISTS(SELECT 1 FROM accounting_allocationrelease r WHERE r.allocation_id=a.id AND r.effective_date<=business_day);
$$;

CREATE FUNCTION accounting_s23_command_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE source accounting_transaction;
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Settlement command is retained' USING ERRCODE='23514',CONSTRAINT='s23_command_immutable'; END IF;
 PERFORM accounting_s19_touch(NEW.office_id);
 IF NEW.operation NOT IN ('ALLOCATE','RELEASE') OR NEW.key_digest !~ '^sha256:[0-9a-f]{64}$' OR
    NEW.payload_digest !~ '^sha256:[0-9a-f]{64}$' OR length(trim(NEW.reason))<4 OR length(NEW.reason)>500 OR
    NEW.expected_count NOT BETWEEN 1 AND 100 OR (NEW.operation='RELEASE' AND NEW.expected_count<>1) THEN
   RAISE EXCEPTION 'Invalid settlement command metadata' USING ERRCODE='23514',CONSTRAINT='s23_command_input';
 END IF;
 IF NEW.actor_id::text IS DISTINCT FROM nullif(current_setting('accounting.s18_actor',true),'') OR
    nullif(current_setting('accounting.s18_command',true),'') IS NOT NULL OR
    NOT EXISTS(SELECT 1 FROM accounting_accountantprofile p JOIN auth_user u ON u.id=p.user_id JOIN accounting_office o ON o.id=p.office_id
      WHERE p.user_id=NEW.actor_id AND p.office_id=NEW.office_id AND p.is_active AND u.is_active AND o.is_active AND
        (NEW.operation='ALLOCATE' OR p.role='owner')) THEN
   RAISE EXCEPTION 'Active settlement actor required' USING ERRCODE='23514',CONSTRAINT='s23_command_actor';
 END IF;
 SELECT * INTO source FROM accounting_transaction WHERE id=NEW.source_cash_id AND office_id=NEW.office_id FOR UPDATE;
 IF NOT FOUND OR source.posting_kind<>'ORDINARY' OR source.entity_id IS NULL OR source.transaction_type NOT IN ('INCOME','EXPENSE') OR
    NEW.effective_date<source.transaction_date OR NEW.effective_date>(clock_timestamp() AT TIME ZONE 'Europe/Athens')::date THEN
   RAISE EXCEPTION 'Eligible dated cash source required' USING ERRCODE='23514',CONSTRAINT='s23_command_source';
 END IF;
 IF TG_OP='INSERT' THEN
   IF NEW.state<>'pending' OR NEW.completed_at IS NOT NULL THEN
     RAISE EXCEPTION 'Settlement command must start pending' USING ERRCODE='23514',CONSTRAINT='s23_command_state';
   END IF;
   NEW.recorded_at:=clock_timestamp();
 ELSE
   IF OLD.state<>'pending' OR NEW.state<>'completed' OR
      (to_jsonb(OLD)-'state'-'completed_at') IS DISTINCT FROM (to_jsonb(NEW)-'state'-'completed_at') THEN
     RAISE EXCEPTION 'Settlement command identity is immutable' USING ERRCODE='23514',CONSTRAINT='s23_command_immutable';
   END IF;
   NEW.completed_at:=clock_timestamp();
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER s23_command_guard BEFORE INSERT OR UPDATE OR DELETE ON accounting_settlementcommand
 FOR EACH ROW EXECUTE FUNCTION accounting_s23_command_guard();

CREATE FUNCTION accounting_s23_allocation_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE cmd accounting_settlementcommand; source accounting_transaction; obligation accounting_charge; d date;
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Allocation is append only' USING ERRCODE='23514',CONSTRAINT='s23_allocation_immutable'; END IF;
 PERFORM accounting_s19_touch(NEW.office_id);
 SELECT * INTO cmd FROM accounting_settlementcommand WHERE id=NEW.command_id AND office_id=NEW.office_id FOR UPDATE;
 IF NOT FOUND OR cmd.state<>'pending' OR cmd.operation<>'ALLOCATE' OR cmd.source_cash_id<>NEW.source_cash_id OR
    cmd.effective_date<>NEW.effective_date OR cmd.actor_id::text IS DISTINCT FROM nullif(current_setting('accounting.s18_actor',true),'') THEN
   RAISE EXCEPTION 'Allocation needs its pending command' USING ERRCODE='23514',CONSTRAINT='s23_allocation_command';
 END IF;
 SELECT * INTO source FROM accounting_transaction WHERE id=NEW.source_cash_id AND office_id=NEW.office_id FOR UPDATE;
 SELECT * INTO obligation FROM accounting_charge WHERE id=NEW.charge_id AND office_id=NEW.office_id FOR UPDATE;
 IF source.id IS NULL OR obligation.id IS NULL OR source.posting_kind<>'ORDINARY' OR source.entity_id IS DISTINCT FROM obligation.entity_id OR
    obligation.direction<>(CASE WHEN source.transaction_type='INCOME' THEN 'RECEIVABLE' ELSE 'PAYABLE' END) OR obligation.currency<>'EUR' OR
    NEW.effective_date<greatest(source.transaction_date,obligation.effective_date) OR
    EXISTS(SELECT 1 FROM accounting_transaction WHERE reversal_of_id=source.id) OR
    NOT EXISTS(SELECT 1 FROM accounting_entity WHERE id=source.entity_id AND office_id=NEW.office_id AND NOT is_archived AND
      CASE WHEN source.transaction_type='INCOME' THEN is_customer ELSE is_supplier END) THEN
   RAISE EXCEPTION 'Allocation source and charge must have the same eligible party and direction' USING ERRCODE='23514',CONSTRAINT='s23_allocation_scope';
 END IF;
 IF NEW.amount<=0 OR NEW.amount>9999999999.99 OR NEW.amount<>round(NEW.amount,2) THEN
   RAISE EXCEPTION 'Allocation needs a positive exact amount' USING ERRCODE='23514',CONSTRAINT='s23_allocation_amount';
 END IF;
 -- Check every affected change point. A later release must not permit a new
 -- backdated allocation which overuses the source/charge before that release.
 FOR d IN
   SELECT NEW.effective_date UNION
   SELECT a.effective_date FROM accounting_cashallocation a WHERE (a.source_cash_id=source.id OR a.charge_id=obligation.id) AND a.effective_date>=NEW.effective_date UNION
   SELECT r.effective_date FROM accounting_allocationrelease r JOIN accounting_cashallocation a ON a.id=r.allocation_id
     WHERE (a.source_cash_id=source.id OR a.charge_id=obligation.id) AND r.effective_date>=NEW.effective_date
 LOOP
   IF accounting_s23_used_at('cash',source.id::text,d)+NEW.amount>source.amount OR
      accounting_s23_used_at('charge',obligation.id::text,d)+NEW.amount>obligation.amount THEN
     RAISE EXCEPTION 'Allocation exceeds dated source availability or outstanding charge' USING ERRCODE='23514',CONSTRAINT='s23_capacity';
   END IF;
 END LOOP;
 NEW.recorded_at:=clock_timestamp(); RETURN NEW;
END $$;
CREATE TRIGGER s23_allocation_guard BEFORE INSERT OR UPDATE OR DELETE ON accounting_cashallocation
 FOR EACH ROW EXECUTE FUNCTION accounting_s23_allocation_guard();

CREATE FUNCTION accounting_s23_release_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE cmd accounting_settlementcommand; allocated accounting_cashallocation;
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Release is append only' USING ERRCODE='23514',CONSTRAINT='s23_release_immutable'; END IF;
 PERFORM accounting_s19_touch(NEW.office_id);
 SELECT * INTO cmd FROM accounting_settlementcommand WHERE id=NEW.command_id AND office_id=NEW.office_id FOR UPDATE;
 SELECT * INTO allocated FROM accounting_cashallocation WHERE id=NEW.allocation_id AND office_id=NEW.office_id FOR UPDATE;
 IF cmd.id IS NULL OR allocated.id IS NULL OR cmd.state<>'pending' OR cmd.operation<>'RELEASE' OR
    cmd.source_cash_id<>allocated.source_cash_id OR cmd.effective_date<>NEW.effective_date OR NEW.effective_date<allocated.effective_date OR
    cmd.actor_id::text IS DISTINCT FROM nullif(current_setting('accounting.s18_actor',true),'') THEN
   RAISE EXCEPTION 'Release needs its original allocation and pending owner command' USING ERRCODE='23514',CONSTRAINT='s23_release_source';
 END IF;
 NEW.recorded_at:=clock_timestamp(); RETURN NEW;
END $$;
CREATE TRIGGER s23_release_guard BEFORE INSERT OR UPDATE OR DELETE ON accounting_allocationrelease
 FOR EACH ROW EXECUTE FUNCTION accounting_s23_release_guard();

CREATE FUNCTION accounting_s23_complete_group() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE cmd accounting_settlementcommand; allocated integer; released integer;
BEGIN
 IF TG_TABLE_NAME='accounting_settlementcommand' THEN SELECT * INTO cmd FROM accounting_settlementcommand WHERE id=NEW.id;
 ELSE SELECT * INTO cmd FROM accounting_settlementcommand WHERE id=NEW.command_id; END IF;
 SELECT count(*) INTO allocated FROM accounting_cashallocation WHERE command_id=cmd.id;
 SELECT count(*) INTO released FROM accounting_allocationrelease WHERE command_id=cmd.id;
 IF cmd.id IS NULL OR cmd.state<>'completed' OR cmd.completed_at IS NULL OR
    (cmd.operation='ALLOCATE' AND (allocated<>cmd.expected_count OR released<>0)) OR
    (cmd.operation='RELEASE' AND (released<>1 OR allocated<>0)) THEN
   RAISE EXCEPTION 'Settlement group must commit completely once' USING ERRCODE='23514',CONSTRAINT='s23_complete_group';
 END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER s23_command_complete AFTER INSERT OR UPDATE ON accounting_settlementcommand
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION accounting_s23_complete_group();
CREATE CONSTRAINT TRIGGER s23_allocation_complete AFTER INSERT ON accounting_cashallocation
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION accounting_s23_complete_group();
CREATE CONSTRAINT TRIGGER s23_release_complete AFTER INSERT ON accounting_allocationrelease
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION accounting_s23_complete_group();

CREATE FUNCTION accounting_s23_cash_reversal_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.posting_kind='REVERSAL' THEN
   PERFORM accounting_s19_touch(NEW.office_id);
   IF EXISTS(SELECT 1 FROM accounting_cashallocation a WHERE a.source_cash_id=NEW.reversal_of_id AND
       (a.effective_date>NEW.transaction_date OR NOT EXISTS(SELECT 1 FROM accounting_allocationrelease r WHERE r.allocation_id=a.id AND r.effective_date<=NEW.transaction_date))) THEN
     RAISE EXCEPTION 'Release allocations before reversing cash; retain dated history' USING ERRCODE='23514',CONSTRAINT='s23_reversal_allocations';
   END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER s23_cash_reversal_guard BEFORE INSERT ON accounting_transaction
 FOR EACH ROW EXECUTE FUNCTION accounting_s23_cash_reversal_guard();
"""

REVERSE = r"""
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM accounting_settlementcommand) OR EXISTS(SELECT 1 FROM accounting_cashallocation) OR EXISTS(SELECT 1 FROM accounting_allocationrelease) THEN
   RAISE EXCEPTION 'Retain S23 settlement history; unsafe downgrade denied' USING ERRCODE='23514';
 END IF;
END $$;
DROP TRIGGER s23_cash_reversal_guard ON accounting_transaction;
DROP FUNCTION accounting_s23_cash_reversal_guard();
DROP TRIGGER s23_release_complete ON accounting_allocationrelease;
DROP TRIGGER s23_allocation_complete ON accounting_cashallocation;
DROP TRIGGER s23_command_complete ON accounting_settlementcommand;
DROP FUNCTION accounting_s23_complete_group();
DROP TRIGGER s23_release_guard ON accounting_allocationrelease;
DROP FUNCTION accounting_s23_release_guard();
DROP TRIGGER s23_allocation_guard ON accounting_cashallocation;
DROP FUNCTION accounting_s23_allocation_guard();
DROP TRIGGER s23_command_guard ON accounting_settlementcommand;
DROP FUNCTION accounting_s23_command_guard();
DROP FUNCTION accounting_s23_used_at(text,text,date);
DROP INDEX s23_source_date;
DROP INDEX s23_charge_date;
ALTER TABLE accounting_allocationrelease DROP CONSTRAINT s23_release_allocation_office;
ALTER TABLE accounting_allocationrelease DROP CONSTRAINT s23_release_command_office;
ALTER TABLE accounting_cashallocation DROP CONSTRAINT s23_allocation_charge_office;
ALTER TABLE accounting_cashallocation DROP CONSTRAINT s23_allocation_cash_office;
ALTER TABLE accounting_cashallocation DROP CONSTRAINT s23_allocation_command_source;
ALTER TABLE accounting_settlementcommand DROP CONSTRAINT s23_command_actor_office;
ALTER TABLE accounting_settlementcommand DROP CONSTRAINT s23_command_cash_office;
ALTER TABLE accounting_cashallocation ALTER COLUMN amount TYPE numeric(12,2);
"""


class Migration(migrations.Migration):
    dependencies = [('accounting', '0017_settlement_foundation')]
    operations = [migrations.RunSQL(FORWARD, REVERSE)]
