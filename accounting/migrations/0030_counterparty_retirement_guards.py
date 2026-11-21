"""Database archive veto, current owner deletion and retained anonymous identity."""
from django.db import migrations

FORWARD = r"""
CREATE FUNCTION accounting_cr005_financial_history(party bigint) RETURNS boolean
 LANGUAGE sql VOLATILE AS $$
 SELECT EXISTS(SELECT 1 FROM accounting_agreement WHERE entity_id=party)
  OR EXISTS(SELECT 1 FROM accounting_transaction WHERE entity_id=party)
  OR EXISTS(SELECT 1 FROM accounting_charge WHERE entity_id=party)
  OR EXISTS(SELECT 1 FROM accounting_agreementtermsversion WHERE entity_id=party)
  OR EXISTS(SELECT 1 FROM accounting_financeauditevent
   WHERE before->>'entity_id'=party::text OR after->>'entity_id'=party::text);
$$;

CREATE FUNCTION accounting_cr005_open_agreements(party bigint, scope uuid, day date)
 RETURNS TABLE(agreement_id bigint, reason text) LANGUAGE sql VOLATILE AS $$
 WITH contracts AS (
  SELECT a.id,a.status,t.billing_mode,t.lifecycle,
   EXISTS(SELECT 1 FROM accounting_agreementtermsversion f
    WHERE f.agreement_id=a.id AND f.office_id=scope AND f.effective_date>day
     AND f.lifecycle IN ('UNREVIEWED','DRAFT','ACTIVE')
     AND NOT EXISTS(SELECT 1 FROM accounting_agreementtermsversion n
      WHERE n.agreement_id=f.agreement_id AND n.office_id=scope
       AND n.revision>f.revision AND n.effective_date<=f.effective_date)) AS future_open
  FROM accounting_agreement a
  LEFT JOIN LATERAL (SELECT v.billing_mode,v.lifecycle FROM accounting_agreementtermsversion v
   WHERE v.agreement_id=a.id AND v.office_id=scope AND v.effective_date<=day
   ORDER BY v.revision DESC LIMIT 1) t ON true
  WHERE a.entity_id=party AND a.office_id=scope
 ), net_charges AS (
  SELECT c.agreement_id,sum(c.amount) AS amount FROM accounting_charge c
  WHERE c.entity_id=party AND c.office_id=scope
   AND NOT EXISTS(SELECT 1 FROM accounting_chargereversal r WHERE r.charge_id=c.id
    AND r.office_id=scope AND r.effective_date<=day)
  GROUP BY c.agreement_id
 ), allocations AS (
  SELECT c.agreement_id,sum(x.amount) AS amount FROM accounting_cashallocation x
  JOIN accounting_charge c ON c.id=x.charge_id
  JOIN accounting_settlementcommand cmd ON cmd.id=x.command_id
  WHERE c.entity_id=party AND x.office_id=scope AND cmd.state='completed' AND x.effective_date<=day
   AND NOT EXISTS(SELECT 1 FROM accounting_allocationrelease r
    JOIN accounting_settlementcommand rc ON rc.id=r.command_id
    WHERE r.allocation_id=x.id AND r.office_id=scope AND r.effective_date<=day AND rc.state='completed')
  GROUP BY c.agreement_id
 ), decisions AS (
  SELECT a.id,CASE
   WHEN coalesce(c.amount,0)-coalesce(x.amount,0)>0 THEN 'outstanding'
   WHEN a.future_open THEN 'future'
   WHEN a.lifecycle IN ('ENDED','CANCELLED') THEN NULL
   WHEN (a.lifecycle IS NULL OR a.lifecycle='UNREVIEWED') AND a.status='CANCELLED' THEN NULL
   WHEN a.lifecycle='ACTIVE' AND a.billing_mode='ONE_OFF'
    AND coalesce(c.amount,0)>0 AND coalesce(c.amount,0)<=coalesce(x.amount,0) THEN NULL
   WHEN a.lifecycle='ACTIVE' AND a.billing_mode='MONTHLY' THEN 'monthly'
   WHEN a.lifecycle='ACTIVE' AND a.billing_mode='ONE_OFF' THEN 'one_off'
   ELSE 'review' END AS blocked
  FROM contracts a LEFT JOIN net_charges c ON c.agreement_id=a.id
   LEFT JOIN allocations x ON x.agreement_id=a.id
 ) SELECT d.id,d.blocked FROM decisions d WHERE d.blocked IS NOT NULL ORDER BY d.id;
$$;

CREATE FUNCTION accounting_cr005_entity_guard() RETURNS trigger LANGUAGE plpgsql VOLATILE AS $$
BEGIN
 IF EXISTS(SELECT 1 FROM accounting_counterpartydeletion WHERE entity_id=OLD.id) THEN
  RAISE EXCEPTION 'Deleted identity is retained and cannot be restored or edited'
   USING ERRCODE='23514',CONSTRAINT='cr005_deleted_retained';
 END IF;
 IF NOT OLD.is_archived AND NEW.is_archived AND EXISTS(
  SELECT 1 FROM accounting_cr005_open_agreements(OLD.id,OLD.office_id,
   (CURRENT_TIMESTAMP AT TIME ZONE 'Europe/Athens')::date)) THEN
  RAISE EXCEPTION 'An open agreement prevents counterparty archive'
   USING ERRCODE='23514',CONSTRAINT='cr005_archive_open';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER cr005_entity_guard BEFORE UPDATE ON accounting_entity
 FOR EACH ROW EXECUTE FUNCTION accounting_cr005_entity_guard();

ALTER TABLE accounting_counterpartydeletion ADD CONSTRAINT cr005_delete_entity_office
 FOREIGN KEY (entity_id,office_id) REFERENCES accounting_entity(id,office_id) DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE accounting_counterpartydeletion ADD CONSTRAINT cr005_delete_actor_office
 FOREIGN KEY (actor_id,office_id) REFERENCES accounting_accountantprofile(user_id,office_id) DEFERRABLE INITIALLY IMMEDIATE;

CREATE FUNCTION accounting_cr005_deletion_guard() RETURNS trigger LANGUAGE plpgsql VOLATILE AS $$
DECLARE person accounting_entity; actor_name text;
BEGIN
 IF TG_OP<>'INSERT' THEN
  RAISE EXCEPTION 'Deletion attribution is append only'
   USING ERRCODE='23514',CONSTRAINT='cr005_delete_immutable';
 END IF;
 PERFORM id FROM accounting_office WHERE id=NEW.office_id AND is_active FOR UPDATE;
 IF NOT FOUND THEN
  RAISE EXCEPTION 'Active office required' USING ERRCODE='23514',CONSTRAINT='cr005_delete_authority';
 END IF;
 SELECT username INTO actor_name FROM auth_user WHERE id=NEW.actor_id AND is_active FOR UPDATE;
 IF NOT FOUND OR nullif(current_setting('accounting.s18_actor',true),'') IS DISTINCT FROM NEW.actor_id::text THEN
  RAISE EXCEPTION 'Current actor context required' USING ERRCODE='23514',CONSTRAINT='cr005_delete_authority';
 END IF;
 PERFORM id FROM accounting_accountantprofile WHERE office_id=NEW.office_id AND user_id=NEW.actor_id
  AND role='owner' AND is_active FOR KEY SHARE;
 IF NOT FOUND THEN
  RAISE EXCEPTION 'Current office owner required' USING ERRCODE='23514',CONSTRAINT='cr005_delete_authority';
 END IF;
 SELECT * INTO person FROM accounting_entity WHERE id=NEW.entity_id AND office_id=NEW.office_id FOR UPDATE;
 IF NOT FOUND OR NOT person.is_archived THEN
  RAISE EXCEPTION 'Archive the same-office identity first' USING ERRCODE='23514',CONSTRAINT='cr005_delete_archived';
 END IF;
 IF accounting_cr005_financial_history(NEW.entity_id) THEN
  RAISE EXCEPTION 'All financial history must be retained' USING ERRCODE='23514',CONSTRAINT='cr005_delete_financial';
 END IF;
 IF person.record_version<>NEW.confirmed_version+1 OR NEW.contact_digest !~ '^sha256:[0-9a-f]{64}$'
  OR person.name<>('Διαγραμμένη εγγραφή #'||person.id::text) OR coalesce(person.vat_number,'')<>''
  OR person.vat_key<>'' OR person.tax_office<>'' OR person.address<>'' OR person.city<>''
  OR person.postal_code<>'' OR person.phone_number<>'' OR person.email<>'' THEN
  RAISE EXCEPTION 'Confirmed version and removed contact values required'
   USING ERRCODE='23514',CONSTRAINT='cr005_delete_payload';
 END IF;
 NEW.actor_label:=actor_name;
 NEW.created_at:=clock_timestamp();
 RETURN NEW;
END $$;
CREATE TRIGGER cr005_deletion_guard BEFORE INSERT OR UPDATE OR DELETE ON accounting_counterpartydeletion
 FOR EACH ROW EXECUTE FUNCTION accounting_cr005_deletion_guard();
"""

REVERSE = r"""
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM accounting_counterpartydeletion) OR
    EXISTS(SELECT 1 FROM accounting_counterpartyevent WHERE action='delete') THEN
  RAISE EXCEPTION 'Retain deletion attribution before any reviewed downgrade';
 END IF;
END $$;
DROP TRIGGER cr005_deletion_guard ON accounting_counterpartydeletion;
DROP FUNCTION accounting_cr005_deletion_guard();
ALTER TABLE accounting_counterpartydeletion DROP CONSTRAINT cr005_delete_actor_office;
ALTER TABLE accounting_counterpartydeletion DROP CONSTRAINT cr005_delete_entity_office;
DROP TRIGGER cr005_entity_guard ON accounting_entity;
DROP FUNCTION accounting_cr005_entity_guard();
DROP FUNCTION accounting_cr005_open_agreements(bigint,uuid,date);
DROP FUNCTION accounting_cr005_financial_history(bigint);
"""


class Migration(migrations.Migration):
    dependencies = [('accounting', '0029_counterparty_retirement')]
    operations = [migrations.RunSQL(FORWARD, REVERSE)]
