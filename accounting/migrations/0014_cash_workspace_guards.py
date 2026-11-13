"""Dated approved opening, immutable signed corrections and serial hierarchy guards.

Schema/DDL access remains the separate trusted operator realm (S16/S18).
"""
import importlib
from django.db import migrations

S18=importlib.import_module('accounting.migrations.0012_financial_database_guards').FORWARD
OLD_SNAPSHOT=S18[S18.index('CREATE FUNCTION accounting_s18_snapshot'):S18.index('-- Baseline records')]
NEW_SNAPSHOT=OLD_SNAPSHOT.replace('CREATE FUNCTION','CREATE OR REPLACE FUNCTION',1).replace(
 "ARRAY['id','office_id','opening_balance','is_active']",
 "ARRAY['id','office_id','opening_balance','opening_date','opening_approved_at','legacy_opening','is_active','record_version']").replace(
 "ARRAY['id','office_id','parent_id']", "ARRAY['id','office_id','parent_id','is_active','record_version']").replace(
 "   ELSE ARRAY[]::text[] END);", "   WHEN 'cashadjustment' THEN ARRAY['id','office_id','account_id','actor_id','amount','effective_date','reversal_of_id','recorded_at']\n   ELSE ARRAY[]::text[] END);")
OLD_AUDIT=S18[S18.index('CREATE FUNCTION accounting_s18_audit()'):S18.index('CREATE TRIGGER s18_cash_audit')]
NEW_AUDIT=OLD_AUDIT.replace('CREATE FUNCTION','CREATE OR REPLACE FUNCTION',1).replace(
 " op:=kind||'.'||lower(TG_OP);", """ op:=kind||'.'||lower(TG_OP);
 IF kind='cashaccount' AND TG_OP='UPDATE' THEN
   IF (to_jsonb(OLD)->>'opening_date') IS NULL AND (val->>'opening_date') IS NOT NULL THEN op:='account.opening.approve';END IF;
 END IF;
 IF kind='cashadjustment' THEN
   business_date:=(val->>'effective_date')::date;
   op:=CASE WHEN (val->>'reversal_of_id') IS NULL THEN 'account.opening.adjust' ELSE 'account.opening.reverse_adjust' END;
 END IF;""")

FORWARD="""
ALTER TABLE accounting_cashadjustment ADD CONSTRAINT s19_adjust_account_office
 FOREIGN KEY(account_id,office_id) REFERENCES accounting_cashaccount(id,office_id) DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE accounting_cashadjustment ADD CONSTRAINT s19_adjust_actor_office
 FOREIGN KEY(actor_id,office_id) REFERENCES accounting_accountantprofile(user_id,office_id) DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE accounting_cashadjustment ADD CONSTRAINT s19_adjust_reversal_office
 FOREIGN KEY(reversal_of_id,office_id) REFERENCES accounting_cashadjustment(id,office_id) DEFERRABLE INITIALLY IMMEDIATE;
CREATE INDEX s19_cash_date_idx ON accounting_transaction(office_id,cash_account_id,transaction_date);

CREATE FUNCTION accounting_s19_touch(off uuid) RETURNS void LANGUAGE plpgsql VOLATILE AS $$
BEGIN
 -- A write, not only an advisory/read lock: Repeatable Read must serialize or
 -- abort a stale hierarchy/account observation instead of allowing write skew.
 INSERT INTO accounting_financestructurelock(office_id,revision) VALUES(off,1)
 ON CONFLICT(office_id) DO UPDATE SET revision=accounting_financestructurelock.revision+1;
END $$;

CREATE FUNCTION accounting_s19_account_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE actor bigint; today date:=(clock_timestamp() AT TIME ZONE 'Europe/Athens')::date;
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Retain cash account and history; deactivate it' USING ERRCODE='23514',CONSTRAINT='s19_account_history';END IF;
 PERFORM accounting_s19_touch(NEW.office_id);
 actor:=nullif(current_setting('accounting.s18_actor',true),'')::bigint;
 IF length(trim(NEW.name))=0 THEN RAISE EXCEPTION 'Account name required' USING ERRCODE='23514',CONSTRAINT='s19_account_name';END IF;
 IF TG_OP='UPDATE' THEN
   IF NEW.legacy_opening IS DISTINCT FROM OLD.legacy_opening THEN RAISE EXCEPTION 'Opening provenance is immutable' USING ERRCODE='23514',CONSTRAINT='s19_opening_provenance';END IF;
   IF OLD.opening_date IS NOT NULL AND
      (NEW.opening_balance,NEW.opening_date,NEW.opening_approved_at,NEW.opening_key_digest,NEW.opening_payload_digest) IS DISTINCT FROM
      (OLD.opening_balance,OLD.opening_date,OLD.opening_approved_at,OLD.opening_key_digest,OLD.opening_payload_digest) THEN
      RAISE EXCEPTION 'Approved opening is immutable; use a dated signed adjustment' USING ERRCODE='23514',CONSTRAINT='s19_opening_immutable';
   END IF;
   IF OLD.opening_date IS NULL THEN
     IF NEW.opening_date IS NULL AND (NEW.opening_balance,NEW.opening_approved_at,NEW.opening_key_digest,NEW.opening_payload_digest) IS DISTINCT FROM
        (OLD.opening_balance,OLD.opening_approved_at,OLD.opening_key_digest,OLD.opening_payload_digest) THEN
       RAISE EXCEPTION 'Opening amount requires approval with its date' USING ERRCODE='23514',CONSTRAINT='s19_opening_pending';
     END IF;
     IF NEW.opening_date IS NOT NULL AND OLD.legacy_opening AND NEW.opening_balance<>OLD.opening_balance THEN
       RAISE EXCEPTION 'Legacy amount is preserved when confirming its cutoff' USING ERRCODE='23514',CONSTRAINT='s19_legacy_opening_amount';
     END IF;
   END IF;
   NEW.record_version:=OLD.record_version+1;
 ELSE
   NEW.record_version:=0;
   IF NEW.opening_date IS NULL AND NEW.opening_balance<>0 THEN NEW.legacy_opening:=true;END IF;
 END IF;
 IF NEW.opening_date IS NOT NULL THEN
   IF NEW.opening_date>today THEN RAISE EXCEPTION 'Future opening not supported' USING ERRCODE='23514',CONSTRAINT='s19_opening_date';END IF;
   IF TG_OP='INSERT' OR OLD.opening_date IS NULL THEN
     IF actor IS NOT NULL AND (NOT EXISTS(SELECT 1 FROM accounting_accountantprofile WHERE user_id=actor AND office_id=NEW.office_id AND role='owner' AND is_active)
        OR NEW.opening_key_digest !~ '^sha256:[0-9a-f]{64}$' OR NEW.opening_payload_digest !~ '^sha256:[0-9a-f]{64}$') THEN
       RAISE EXCEPTION 'Opening approval requires its office owner command' USING ERRCODE='23514',CONSTRAINT='s19_opening_authority';
     END IF;
     NEW.opening_approved_at:=clock_timestamp();
   END IF;
 ELSE
   IF NEW.opening_approved_at IS NOT NULL OR NEW.opening_key_digest<>'' OR NEW.opening_payload_digest<>'' THEN
     RAISE EXCEPTION 'Unreviewed opening cannot have approval metadata' USING ERRCODE='23514',CONSTRAINT='s19_opening_pending';
   END IF;
   IF TG_OP='INSERT' AND actor IS NOT NULL AND NEW.opening_balance<>0 THEN
     RAISE EXCEPTION 'Staff create pending accounts before opening approval' USING ERRCODE='23514',CONSTRAINT='s19_opening_authority';
   END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER s19_account_guard BEFORE INSERT OR UPDATE OR DELETE ON accounting_cashaccount
 FOR EACH ROW EXECUTE FUNCTION accounting_s19_account_guard();

CREATE FUNCTION accounting_s19_category_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE key bigint; link record; visited bigint[]; depth integer:=0;
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Retire categories; retain labels, links and history' USING ERRCODE='23514',CONSTRAINT='s19_category_history';END IF;
 PERFORM accounting_s19_touch(NEW.office_id);
 IF length(trim(NEW.name))=0 THEN RAISE EXCEPTION 'Category name required' USING ERRCODE='23514',CONSTRAINT='s19_category_name';END IF;
 visited:=ARRAY[NEW.id];key:=NEW.parent_id;
 WHILE key IS NOT NULL LOOP
   depth:=depth+1;
   IF key=ANY(visited) OR depth>63 THEN RAISE EXCEPTION 'Category cycle or excessive depth' USING ERRCODE='23514',CONSTRAINT='s19_category_cycle';END IF;
   visited:=visited||key;
   SELECT parent_id,is_active INTO link FROM accounting_category WHERE id=key AND office_id=NEW.office_id;
   IF NOT FOUND OR (NEW.is_active AND NOT link.is_active) THEN RAISE EXCEPTION 'Active same-office category parent required' USING ERRCODE='23514',CONSTRAINT='s19_category_parent';END IF;
   key:=link.parent_id;
 END LOOP;
 IF TG_OP='UPDATE' THEN
   IF OLD.is_active AND NOT NEW.is_active AND EXISTS(SELECT 1 FROM accounting_category WHERE parent_id=OLD.id AND office_id=OLD.office_id AND is_active) THEN
     RAISE EXCEPTION 'Retire or move active child categories first' USING ERRCODE='23514',CONSTRAINT='s19_category_children';
   END IF;
   NEW.record_version:=OLD.record_version+1;
 ELSE NEW.record_version:=0;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER s19_category_guard BEFORE INSERT OR UPDATE OR DELETE ON accounting_category
 FOR EACH ROW EXECUTE FUNCTION accounting_s19_category_guard();

CREATE FUNCTION accounting_s19_cash_scope() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE acc accounting_cashaccount;
BEGIN
 PERFORM accounting_s19_touch(NEW.office_id);
 SELECT * INTO acc FROM accounting_cashaccount WHERE id=NEW.cash_account_id AND office_id=NEW.office_id;
 IF NOT FOUND OR acc.opening_date IS NULL OR NEW.transaction_date<acc.opening_date OR
   (NEW.posting_kind<>'REVERSAL' AND NOT acc.is_active) THEN
   RAISE EXCEPTION 'Cash account opening/date/activity not valid' USING ERRCODE='23514',CONSTRAINT='s19_cash_opening';
 END IF;
 IF NEW.posting_kind<>'REVERSAL' AND NEW.category_id IS NOT NULL AND NOT EXISTS(
     SELECT 1 FROM accounting_category WHERE id=NEW.category_id AND office_id=NEW.office_id AND is_active) THEN
   RAISE EXCEPTION 'Retired category cannot receive new work' USING ERRCODE='23514',CONSTRAINT='s19_retired_category';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER s19_cash_scope BEFORE INSERT ON accounting_transaction FOR EACH ROW EXECUTE FUNCTION accounting_s19_cash_scope();

CREATE FUNCTION accounting_s19_adjust_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE acc accounting_cashaccount; original accounting_cashadjustment; actor bigint;
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Opening adjustments are immutable' USING ERRCODE='23514',CONSTRAINT='s19_adjust_immutable';END IF;
 PERFORM accounting_s19_touch(NEW.office_id);
 SELECT * INTO acc FROM accounting_cashaccount WHERE id=NEW.account_id AND office_id=NEW.office_id;
 IF NOT FOUND OR acc.opening_date IS NULL OR NEW.effective_date<acc.opening_date OR NEW.effective_date>(clock_timestamp() AT TIME ZONE 'Europe/Athens')::date THEN
   RAISE EXCEPTION 'Adjustment needs a reviewed account opening and valid date' USING ERRCODE='23514',CONSTRAINT='s19_adjust_date';
 END IF;
 actor:=nullif(current_setting('accounting.s18_actor',true),'')::bigint;
 IF actor IS NOT NULL THEN
   IF NEW.actor_id IS DISTINCT FROM actor OR NOT EXISTS(SELECT 1 FROM accounting_accountantprofile WHERE user_id=actor AND office_id=NEW.office_id AND role='owner' AND is_active)
       OR NEW.effective_date<>(clock_timestamp() AT TIME ZONE 'Europe/Athens')::date THEN
     RAISE EXCEPTION 'Owner correction authority and current business day required' USING ERRCODE='23514',CONSTRAINT='s19_adjust_owner';
   END IF;
 ELSIF NEW.actor_id IS NOT NULL THEN RAISE EXCEPTION 'Operator adjustment must not invent a human actor' USING ERRCODE='23514',CONSTRAINT='s19_adjust_owner';
 END IF;
 IF nullif(current_setting('accounting.s18_command',true),'') IS NOT NULL OR NEW.key_digest !~ '^sha256:[0-9a-f]{64}$' OR NEW.payload_digest !~ '^sha256:[0-9a-f]{64}$' OR length(trim(NEW.reason))<4 OR length(trim(NEW.review_reference))<4 THEN
   RAISE EXCEPTION 'Adjustment identity and evidence required' USING ERRCODE='23514',CONSTRAINT='s19_adjust_identity';
 END IF;
 IF NEW.reversal_of_id IS NOT NULL THEN
   SELECT * INTO original FROM accounting_cashadjustment WHERE id=NEW.reversal_of_id AND office_id=NEW.office_id AND account_id=NEW.account_id;
   IF NOT FOUND OR original.reversal_of_id IS NOT NULL OR NEW.amount<>-original.amount OR NEW.effective_date<original.effective_date THEN
     RAISE EXCEPTION 'Adjustment reversal must negate its same-account original' USING ERRCODE='23514',CONSTRAINT='s19_adjust_reversal';
   END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER s19_adjust_guard BEFORE INSERT OR UPDATE OR DELETE ON accounting_cashadjustment
 FOR EACH ROW EXECUTE FUNCTION accounting_s19_adjust_guard();
CREATE TRIGGER s19_adjust_audit AFTER INSERT ON accounting_cashadjustment
 FOR EACH ROW EXECUTE FUNCTION accounting_s18_audit();

CREATE FUNCTION accounting_s19_adjust_complete() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF (SELECT count(*) FROM accounting_financeauditevent WHERE office_id=NEW.office_id AND target_model='cashadjustment' AND target_id=NEW.id)<>1 THEN
  RAISE EXCEPTION 'Adjustment and audit must commit together' USING ERRCODE='23514',CONSTRAINT='s19_adjust_audit';
 END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER s19_adjust_complete AFTER INSERT ON accounting_cashadjustment DEFERRABLE INITIALLY DEFERRED
 FOR EACH ROW EXECUTE FUNCTION accounting_s19_adjust_complete();
"""+NEW_SNAPSHOT+NEW_AUDIT

REVERSE="""
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM accounting_cashaccount WHERE opening_date IS NOT NULL OR record_version>0) OR
    EXISTS(SELECT 1 FROM accounting_category WHERE NOT is_active OR record_version>0) OR EXISTS(SELECT 1 FROM accounting_cashadjustment) THEN
   RAISE EXCEPTION 'S19 downgrade requires a reviewed opening/category/audit preservation plan';
 END IF;
END $$;
DROP TRIGGER s19_adjust_complete ON accounting_cashadjustment;
DROP FUNCTION accounting_s19_adjust_complete();
DROP TRIGGER s19_adjust_audit ON accounting_cashadjustment;
DROP TRIGGER s19_adjust_guard ON accounting_cashadjustment;
DROP FUNCTION accounting_s19_adjust_guard();
DROP TRIGGER s19_cash_scope ON accounting_transaction;
DROP FUNCTION accounting_s19_cash_scope();
DROP TRIGGER s19_category_guard ON accounting_category;
DROP FUNCTION accounting_s19_category_guard();
DROP TRIGGER s19_account_guard ON accounting_cashaccount;
DROP FUNCTION accounting_s19_account_guard();
DROP FUNCTION accounting_s19_touch(uuid);
DROP INDEX s19_cash_date_idx;
ALTER TABLE accounting_cashadjustment DROP CONSTRAINT s19_adjust_reversal_office;
ALTER TABLE accounting_cashadjustment DROP CONSTRAINT s19_adjust_actor_office;
ALTER TABLE accounting_cashadjustment DROP CONSTRAINT s19_adjust_account_office;
"""+OLD_SNAPSHOT.replace('CREATE FUNCTION','CREATE OR REPLACE FUNCTION',1)+OLD_AUDIT.replace('CREATE FUNCTION','CREATE OR REPLACE FUNCTION',1)

class Migration(migrations.Migration):
 dependencies=[('accounting','0013_cash_accounts_categories')]
 operations=[migrations.RunSQL(FORWARD,REVERSE)]
