"""Immutable cash originals, auditable database writes, deferred operation groups.

A role that owns schema/DDL can disable triggers: operator access is a separate
trust realm, as in S16. No SECURITY DEFINER or elevated role is needed.
"""
import importlib
from django.db import migrations

S15_FORWARD=importlib.import_module('accounting.migrations.0010_counterparty_database_guards').FORWARD
S15_LINK=S15_FORWARD[S15_FORWARD.index('CREATE FUNCTION accounting_s15_active_links()'):S15_FORWARD.index('CREATE TRIGGER s15_agreement_active')]
S18_LINK=S15_LINK.replace('CREATE FUNCTION','CREATE OR REPLACE FUNCTION',1).replace(
 ' -- Match the office-before-entity',
 " IF TG_TABLE_NAME='accounting_transaction' THEN\n   IF NEW.posting_kind='REVERSAL' THEN RETURN NEW; END IF;\n END IF;\n -- Match the office-before-entity")

FORWARD="""
ALTER TABLE accounting_financecommand ADD CONSTRAINT s18_command_actor_office
 FOREIGN KEY(actor_id,office_id) REFERENCES accounting_accountantprofile(user_id,office_id) DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE accounting_transaction ADD CONSTRAINT s18_entry_command_office
 FOREIGN KEY(command_id,office_id) REFERENCES accounting_financecommand(id,office_id) DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE accounting_transaction ADD CONSTRAINT s18_reversal_office
 FOREIGN KEY(reversal_of_id,office_id) REFERENCES accounting_transaction(id,office_id) DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE accounting_financeauditevent ADD CONSTRAINT s18_audit_actor_office
 FOREIGN KEY(actor_id,office_id) REFERENCES accounting_accountantprofile(user_id,office_id) DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE accounting_financeauditevent ADD CONSTRAINT s18_audit_entry_office
 FOREIGN KEY(entry_id,office_id) REFERENCES accounting_transaction(id,office_id) DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE accounting_financeauditevent ADD CONSTRAINT s18_audit_command_office
 FOREIGN KEY(command_id,office_id) REFERENCES accounting_financecommand(id,office_id) DEFERRABLE INITIALLY IMMEDIATE;

CREATE FUNCTION accounting_s18_snapshot(kind text,value jsonb) RETURNS jsonb LANGUAGE sql IMMUTABLE AS $$
 SELECT coalesce(jsonb_object_agg(key,CASE WHEN key IN ('amount','total_amount','opening_balance') THEN to_jsonb(val #>> '{}') ELSE val END),'{}'::jsonb) FROM jsonb_each(value) AS fields(key,val)
 WHERE key=ANY(CASE kind
   WHEN 'transaction' THEN ARRAY['id','office_id','amount','transaction_date','transaction_type','cash_account_id','category_id','entity_id','agreement_id','posting_kind','reversal_of_id','transfer_id','command_id']
   WHEN 'agreement' THEN ARRAY['id','office_id','entity_id','total_amount','agreement_type','status','start_date']
   WHEN 'cashaccount' THEN ARRAY['id','office_id','opening_balance','is_active']
   WHEN 'category' THEN ARRAY['id','office_id','parent_id']
   ELSE ARRAY[]::text[] END);
$$;

-- Baseline records the observed migration state, not an invented historical human.
INSERT INTO accounting_financeauditevent(office_id,actor_id,database_actor,origin,operation,target_model,target_id,entry_id,command_id,before,after,reason,effective_date,recorded_at)
 SELECT office_id,NULL,current_user,'legacy','legacy.baseline','transaction',id,id,NULL,'{}',accounting_s18_snapshot('transaction',to_jsonb(t)),
 'Αρχική απογραφή διατηρημένης κίνησης· ο αρχικός χρήστης δεν είναι γνωστός',transaction_date,clock_timestamp() FROM accounting_transaction t;
INSERT INTO accounting_financeauditevent(office_id,actor_id,database_actor,origin,operation,target_model,target_id,entry_id,command_id,before,after,reason,effective_date,recorded_at)
 SELECT office_id,NULL,current_user,'legacy','legacy.baseline','agreement',id,NULL,NULL,'{}',accounting_s18_snapshot('agreement',to_jsonb(t)),
 'Αρχική απογραφή οικονομικών στοιχείων',start_date,clock_timestamp() FROM accounting_agreement t;
INSERT INTO accounting_financeauditevent(office_id,actor_id,database_actor,origin,operation,target_model,target_id,entry_id,command_id,before,after,reason,effective_date,recorded_at)
 SELECT office_id,NULL,current_user,'legacy','legacy.baseline','cashaccount',id,NULL,NULL,'{}',accounting_s18_snapshot('cashaccount',to_jsonb(t)),
 'Αρχική απογραφή οικονομικών στοιχείων',NULL,clock_timestamp() FROM accounting_cashaccount t;
INSERT INTO accounting_financeauditevent(office_id,actor_id,database_actor,origin,operation,target_model,target_id,entry_id,command_id,before,after,reason,effective_date,recorded_at)
 SELECT office_id,NULL,current_user,'legacy','legacy.baseline','category',id,NULL,NULL,'{}',accounting_s18_snapshot('category',to_jsonb(t)),
 'Αρχική απογραφή οικονομικών στοιχείων',NULL,clock_timestamp() FROM accounting_category t;

CREATE FUNCTION accounting_s18_audit_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP<>'INSERT' OR pg_trigger_depth()<2 THEN
   RAISE EXCEPTION 'Financial audit is database-written and append only' USING ERRCODE='23514',CONSTRAINT='s18_audit_immutable';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER s18_audit_guard BEFORE INSERT OR UPDATE OR DELETE ON accounting_financeauditevent
 FOR EACH ROW EXECUTE FUNCTION accounting_s18_audit_guard();

CREATE FUNCTION accounting_s18_audit() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE a bigint; cmd uuid; off uuid; before_value jsonb:='{}'; after_value jsonb:='{}';
 val jsonb; kind text; why text; op text; source text; business_date date; ent bigint;
BEGIN
 IF TG_OP='DELETE' THEN val:=to_jsonb(OLD); ELSE val:=to_jsonb(NEW); END IF;
 kind:=substr(TG_TABLE_NAME,length('accounting_')+1);off:=(val->>'office_id')::uuid;
 a:=nullif(current_setting('accounting.s18_actor',true),'')::bigint;
 cmd:=nullif(current_setting('accounting.s18_command',true),'')::uuid;
 IF a IS NOT NULL THEN
   IF NOT EXISTS(SELECT 1 FROM accounting_accountantprofile p JOIN auth_user u ON u.id=p.user_id
                 JOIN accounting_office o ON o.id=p.office_id
                 WHERE p.user_id=a AND p.office_id=off AND p.is_active AND u.is_active AND o.is_active) THEN
     RAISE EXCEPTION 'Audit actor does not have active office authority' USING ERRCODE='23514',CONSTRAINT='s18_audit_actor';
   END IF;
   source:='user';why:=nullif(current_setting('accounting.s18_reason',true),'');
   IF why IS NULL OR length(why)>500 THEN RAISE EXCEPTION 'Audit reason required' USING ERRCODE='23514',CONSTRAINT='s18_audit_reason';END IF;
 ELSE
   source:='database';why:='Διαχειριστική εγγραφή από τον αναγραφόμενο ρόλο βάσης';cmd:=NULL;
 END IF;
 IF TG_OP<>'INSERT' THEN before_value:=accounting_s18_snapshot(kind,to_jsonb(OLD));END IF;
 IF TG_OP<>'DELETE' THEN after_value:=accounting_s18_snapshot(kind,to_jsonb(NEW));END IF;
 IF TG_OP='UPDATE' THEN
   IF (to_jsonb(OLD)-'updated_at')=(to_jsonb(NEW)-'updated_at') THEN RETURN NEW; END IF;
   -- Field names expose the kind of change without copying arbitrary free text.
   after_value:=after_value||jsonb_build_object('changed_fields',
      (SELECT coalesce(jsonb_agg(key ORDER BY key),'[]') FROM jsonb_each(to_jsonb(NEW)) AS fields(key,value)
       WHERE key<>'updated_at' AND value IS DISTINCT FROM (to_jsonb(OLD)->key)));
 END IF;
 op:=kind||'.'||lower(TG_OP);
 IF kind='transaction' THEN
   ent:=(val->>'id')::bigint;business_date:=(val->>'transaction_date')::date;
   IF (val->>'command_id') IS DISTINCT FROM cmd::text THEN
     RAISE EXCEPTION 'Cash command and audit context differ' USING ERRCODE='23514',CONSTRAINT='s18_audit_command';
   END IF;
   IF cmd IS NOT NULL THEN SELECT operation INTO op FROM accounting_financecommand WHERE id=cmd;END IF;
 ELSIF kind='agreement' THEN business_date:=(val->>'start_date')::date;
 END IF;
 INSERT INTO accounting_financeauditevent(office_id,actor_id,database_actor,origin,operation,target_model,target_id,entry_id,command_id,before,after,reason,effective_date,recorded_at)
 VALUES(off,a,current_user,source,op,kind,(val->>'id')::bigint,ent,cmd,before_value,after_value,why,business_date,clock_timestamp());
 IF TG_OP='DELETE' THEN RETURN OLD;ELSE RETURN NEW;END IF;
END $$;
CREATE TRIGGER s18_cash_audit AFTER INSERT ON accounting_transaction FOR EACH ROW EXECUTE FUNCTION accounting_s18_audit();
CREATE TRIGGER s18_agreement_audit AFTER INSERT OR UPDATE OR DELETE ON accounting_agreement FOR EACH ROW EXECUTE FUNCTION accounting_s18_audit();
CREATE TRIGGER s18_account_audit AFTER INSERT OR UPDATE OR DELETE ON accounting_cashaccount FOR EACH ROW EXECUTE FUNCTION accounting_s18_audit();
CREATE TRIGGER s18_category_audit AFTER INSERT OR UPDATE OR DELETE ON accounting_category FOR EACH ROW EXECUTE FUNCTION accounting_s18_audit();

CREATE FUNCTION accounting_s18_cash_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE original accounting_transaction; command accounting_financecommand; linked accounting_agreement;
BEGIN
 IF TG_OP<>'INSERT' THEN
   RAISE EXCEPTION 'Posted cash is immutable; append a linked reversal' USING ERRCODE='23514',CONSTRAINT='s18_cash_immutable';
 END IF;
 IF NEW.transaction_type NOT IN ('INCOME','EXPENSE') OR NEW.transaction_date>CURRENT_DATE THEN
   RAISE EXCEPTION 'Invalid cash type or future date' USING ERRCODE='23514',CONSTRAINT='s18_cash_input';
 END IF;
 IF NEW.command_id IS NOT NULL THEN
   SELECT * INTO command FROM accounting_financecommand WHERE id=NEW.command_id AND office_id=NEW.office_id FOR UPDATE;
   IF NOT FOUND OR command.state<>'pending' OR command.actor_id::text IS DISTINCT FROM nullif(current_setting('accounting.s18_actor',true),'') THEN
     RAISE EXCEPTION 'Cash command is not open for this actor' USING ERRCODE='23514',CONSTRAINT='s18_cash_command';
   END IF;
 ELSIF NEW.posting_kind<>'LEGACY' THEN
   RAISE EXCEPTION 'New postings require a command' USING ERRCODE='23514',CONSTRAINT='s18_cash_command';
 END IF;
 IF NEW.posting_kind='REVERSAL' THEN
   SELECT * INTO original FROM accounting_transaction WHERE id=NEW.reversal_of_id AND office_id=NEW.office_id FOR UPDATE;
   IF NOT FOUND OR original.posting_kind IN ('REVERSAL','TRANSFER') OR
      EXISTS(SELECT 1 FROM accounting_transaction WHERE transfer_id=original.transfer_id AND office_id=original.office_id AND id<>original.id) OR
      command.operation NOT IN ('cash.reverse','cash.correct') OR
      NEW.amount<>original.amount OR NEW.transaction_date<original.transaction_date OR
      NEW.transaction_type=original.transaction_type OR
      (NEW.cash_account_id,NEW.entity_id,NEW.category_id,NEW.agreement_id) IS DISTINCT FROM
      (original.cash_account_id,original.entity_id,original.category_id,original.agreement_id) THEN
     RAISE EXCEPTION 'Reversal must exactly negate one eligible retained source' USING ERRCODE='23514',CONSTRAINT='s18_reversal_source';
   END IF;
 ELSE
   IF NOT EXISTS(SELECT 1 FROM accounting_cashaccount WHERE id=NEW.cash_account_id AND office_id=NEW.office_id AND is_active) THEN
     RAISE EXCEPTION 'Cash account is not active' USING ERRCODE='23514',CONSTRAINT='s18_active_account';
   END IF;
   IF NEW.entity_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM accounting_entity WHERE id=NEW.entity_id AND office_id=NEW.office_id
       AND CASE WHEN NEW.transaction_type='INCOME' THEN is_customer ELSE is_supplier END) THEN
     RAISE EXCEPTION 'Counterparty role does not match cash direction' USING ERRCODE='23514',CONSTRAINT='s18_cash_role';
   END IF;
   IF NEW.agreement_id IS NOT NULL THEN
     SELECT * INTO linked FROM accounting_agreement WHERE id=NEW.agreement_id AND office_id=NEW.office_id;
     IF NOT FOUND OR NEW.entity_id IS DISTINCT FROM linked.entity_id OR linked.status='CANCELLED' OR
        linked.agreement_type<>(CASE WHEN NEW.transaction_type='INCOME' THEN 'RECEIVABLE' ELSE 'PAYABLE' END) THEN
       RAISE EXCEPTION 'Cash settlement reference is invalid' USING ERRCODE='23514',CONSTRAINT='s18_settlement_reference';
     END IF;
   END IF;
   IF NEW.posting_kind='TRANSFER' AND (command.operation<>'cash.transfer' OR NEW.entity_id IS NOT NULL OR NEW.agreement_id IS NOT NULL OR NEW.category_id IS NOT NULL) THEN
     RAISE EXCEPTION 'Transfer legs have no allocation targets' USING ERRCODE='23514',CONSTRAINT='s18_transfer_reference';
   END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER s18_cash_guard BEFORE INSERT OR UPDATE OR DELETE ON accounting_transaction FOR EACH ROW EXECUTE FUNCTION accounting_s18_cash_guard();

CREATE FUNCTION accounting_s18_command_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Posting command is retained' USING ERRCODE='23514',CONSTRAINT='s18_command_immutable';END IF;
 IF NEW.operation NOT IN ('cash.post','cash.transfer','cash.reverse','cash.correct') OR NEW.key_digest !~ '^sha256:[0-9a-f]{64}$' OR NEW.payload_digest !~ '^sha256:[0-9a-f]{64}$' OR length(trim(NEW.reason))<4 THEN
   RAISE EXCEPTION 'Invalid posting command' USING ERRCODE='23514',CONSTRAINT='s18_command_input';
 END IF;
 IF TG_OP='UPDATE' AND (OLD.state<>'pending' OR NEW.state<>'completed' OR
      (to_jsonb(OLD)-'state'-'completed_at') IS DISTINCT FROM (to_jsonb(NEW)-'state'-'completed_at')) THEN
   RAISE EXCEPTION 'Posting command identity is immutable' USING ERRCODE='23514',CONSTRAINT='s18_command_immutable';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER s18_command_guard BEFORE INSERT OR UPDATE OR DELETE ON accounting_financecommand FOR EACH ROW EXECUTE FUNCTION accounting_s18_command_guard();

CREATE FUNCTION accounting_s18_complete_group() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE cmd accounting_financecommand; n integer; reversals integer; ordinary integer; a accounting_transaction; b accounting_transaction;
BEGIN
 IF TG_TABLE_NAME='accounting_transaction' THEN SELECT * INTO cmd FROM accounting_financecommand WHERE id=NEW.command_id;
 ELSE SELECT * INTO cmd FROM accounting_financecommand WHERE id=NEW.id; END IF;
 IF cmd.id IS NULL THEN RETURN NULL; END IF;
 SELECT count(*),count(*) FILTER(WHERE posting_kind='REVERSAL'),count(*) FILTER(WHERE posting_kind='ORDINARY')
   INTO n,reversals,ordinary FROM accounting_transaction WHERE command_id=cmd.id;
 IF cmd.state<>'completed' OR cmd.completed_at IS NULL OR n<>(CASE WHEN cmd.operation IN('cash.transfer','cash.correct') THEN 2 ELSE 1 END) OR
    n<>(SELECT count(*) FROM accounting_financeauditevent WHERE command_id=cmd.id AND entry_id IS NOT NULL) THEN
   RAISE EXCEPTION 'Incomplete atomic financial group' USING ERRCODE='23514',CONSTRAINT='s18_complete_group';
 END IF;
 IF (cmd.operation='cash.post' AND ordinary<>1) OR (cmd.operation='cash.reverse' AND reversals<>1) OR
    (cmd.operation='cash.correct' AND (ordinary<>1 OR reversals<>1)) THEN
   RAISE EXCEPTION 'Wrong cash operation members' USING ERRCODE='23514',CONSTRAINT='s18_complete_group';
 END IF;
 IF cmd.operation='cash.transfer' THEN
   SELECT * INTO a FROM accounting_transaction WHERE command_id=cmd.id ORDER BY id LIMIT 1;
   SELECT * INTO b FROM accounting_transaction WHERE command_id=cmd.id ORDER BY id DESC LIMIT 1;
   IF a.posting_kind<>'TRANSFER' OR b.posting_kind<>'TRANSFER' OR a.transfer_id<>b.transfer_id OR a.cash_account_id=b.cash_account_id OR
      a.transaction_type=b.transaction_type OR a.amount<>b.amount OR a.transaction_date<>b.transaction_date THEN
     RAISE EXCEPTION 'Transfer pair must balance' USING ERRCODE='23514',CONSTRAINT='s18_transfer_pair';
   END IF;
 END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER s18_complete_command AFTER INSERT OR UPDATE ON accounting_financecommand DEFERRABLE INITIALLY DEFERRED
 FOR EACH ROW EXECUTE FUNCTION accounting_s18_complete_group();
CREATE CONSTRAINT TRIGGER s18_complete_cash AFTER INSERT ON accounting_transaction DEFERRABLE INITIALLY DEFERRED
 FOR EACH ROW EXECUTE FUNCTION accounting_s18_complete_group();
"""+S18_LINK

REVERSE="""
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM accounting_financecommand) OR EXISTS(SELECT 1 FROM accounting_transaction WHERE posting_kind<>'LEGACY') THEN
  RAISE EXCEPTION 'S18 downgrade requires a reviewed ledger/audit preservation plan';
 END IF;
END $$;
DROP TRIGGER s18_complete_cash ON accounting_transaction;
DROP TRIGGER s18_complete_command ON accounting_financecommand;
DROP FUNCTION accounting_s18_complete_group();
DROP TRIGGER s18_command_guard ON accounting_financecommand;
DROP FUNCTION accounting_s18_command_guard();
DROP TRIGGER s18_cash_guard ON accounting_transaction;
DROP FUNCTION accounting_s18_cash_guard();
DROP TRIGGER s18_category_audit ON accounting_category;
DROP TRIGGER s18_account_audit ON accounting_cashaccount;
DROP TRIGGER s18_agreement_audit ON accounting_agreement;
DROP TRIGGER s18_cash_audit ON accounting_transaction;
DROP FUNCTION accounting_s18_audit();
DROP TRIGGER s18_audit_guard ON accounting_financeauditevent;
DROP FUNCTION accounting_s18_audit_guard();
DROP FUNCTION accounting_s18_snapshot(text,jsonb);
ALTER TABLE accounting_financeauditevent DROP CONSTRAINT s18_audit_command_office;
ALTER TABLE accounting_financeauditevent DROP CONSTRAINT s18_audit_entry_office;
ALTER TABLE accounting_financeauditevent DROP CONSTRAINT s18_audit_actor_office;
ALTER TABLE accounting_transaction DROP CONSTRAINT s18_reversal_office;
ALTER TABLE accounting_transaction DROP CONSTRAINT s18_entry_command_office;
ALTER TABLE accounting_financecommand DROP CONSTRAINT s18_command_actor_office;
"""+S15_LINK.replace('CREATE FUNCTION','CREATE OR REPLACE FUNCTION',1)

class Migration(migrations.Migration):
 dependencies=[('accounting','0011_financial_posting_foundation')]
 operations=[migrations.RunSQL(FORWARD,REVERSE)]
