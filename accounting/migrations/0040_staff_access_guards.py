"""Keep credential commands office-scoped, attributed and monotonic."""
from django.db import migrations

FORWARD = r"""
ALTER TABLE accounting_staffcredentialrequirement ADD CONSTRAINT cr011_target_office
 FOREIGN KEY(user_id,office_id) REFERENCES accounting_accountantprofile(user_id,office_id) DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE accounting_staffcredentialrequirement ADD CONSTRAINT cr011_issuer_office
 FOREIGN KEY(issued_by_id,office_id) REFERENCES accounting_accountantprofile(user_id,office_id) DEFERRABLE INITIALLY IMMEDIATE;
CREATE FUNCTION accounting_cr011_credential_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE actor bigint; action text; actual_marker text; actual_revision bigint;
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Retain staff credential attribution' USING ERRCODE='23514'; END IF;
 actor:=nullif(current_setting('accounting.cr011_actor',true),'')::bigint;
 action:=nullif(current_setting('accounting.cr011_action',true),'');
 PERFORM id FROM accounting_office WHERE id=NEW.office_id AND is_active FOR UPDATE;
 IF NOT FOUND OR actor IS NULL THEN RAISE EXCEPTION 'Explicit active office credential actor required' USING ERRCODE='23514'; END IF;
 PERFORM u.id FROM auth_user u JOIN accounting_accountantprofile p ON p.user_id=u.id
 WHERE u.id=actor AND u.is_active AND p.office_id=NEW.office_id AND p.is_active
 AND p.role IN('owner','accountant') FOR KEY SHARE OF u,p;
 IF NOT FOUND THEN RAISE EXCEPTION 'Fresh same-office credential actor required' USING ERRCODE='23514'; END IF;
 SELECT 'sha256:'||encode(sha256(convert_to(u.password,'UTF8')),'hex'),s.revision INTO actual_marker,actual_revision
 FROM auth_user u JOIN accounting_authsecuritystate s ON s.user_id=u.id
 WHERE u.id=NEW.user_id AND NOT u.is_staff AND NOT u.is_superuser FOR KEY SHARE OF u,s;
 IF NOT FOUND OR actual_marker IS DISTINCT FROM NEW.password_marker OR actual_revision IS DISTINCT FROM NEW.security_revision THEN
  RAISE EXCEPTION 'Exact target password and security revision required' USING ERRCODE='23514';
 END IF;
 IF TG_OP='UPDATE' AND ((NEW.user_id,NEW.office_id) IS DISTINCT FROM (OLD.user_id,OLD.office_id)
   OR NEW.version<>OLD.version+1 OR NEW.security_revision<=OLD.security_revision OR NEW.password_marker=OLD.password_marker) THEN
  RAISE EXCEPTION 'Credential identity and revision are retained' USING ERRCODE='23514';
 END IF;
 IF action='ISSUE' THEN
  PERFORM 1 FROM accounting_accountantprofile WHERE user_id=actor AND office_id=NEW.office_id AND role='owner' AND is_active;
  IF NOT FOUND OR EXISTS(SELECT 1 FROM accounting_staffcredentialrequirement WHERE user_id=actor AND required)
     OR actor=NEW.user_id OR NEW.issued_by_id<>actor OR NOT NEW.required
     OR (TG_OP='INSERT' AND NEW.version<>0) THEN
   RAISE EXCEPTION 'Only another same-office owner may issue temporary credentials' USING ERRCODE='23514';
  END IF;
  NEW.issued_at:=clock_timestamp(); NEW.changed_at:=NULL;
 ELSIF action='CHANGE' AND TG_OP='UPDATE' THEN
  IF actor<>NEW.user_id OR NOT OLD.required OR NEW.required
     OR (NEW.issued_by_id,NEW.issued_at) IS DISTINCT FROM (OLD.issued_by_id,OLD.issued_at) THEN
   RAISE EXCEPTION 'Only the pending user may finish a required change' USING ERRCODE='23514';
  END IF;
  NEW.changed_at:=clock_timestamp();
 ELSE RAISE EXCEPTION 'Explicit credential command required' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER cr011_credential_guard BEFORE INSERT OR UPDATE OR DELETE ON accounting_staffcredentialrequirement
 FOR EACH ROW EXECUTE FUNCTION accounting_cr011_credential_guard();
"""
REVERSE = r"""
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM accounting_staffcredentialrequirement) THEN
  RAISE EXCEPTION 'Retain staff credential attribution before downgrade';
 END IF;
END $$;
DROP TRIGGER cr011_credential_guard ON accounting_staffcredentialrequirement;
DROP FUNCTION accounting_cr011_credential_guard();
ALTER TABLE accounting_staffcredentialrequirement DROP CONSTRAINT cr011_issuer_office;
ALTER TABLE accounting_staffcredentialrequirement DROP CONSTRAINT cr011_target_office;
"""


class Migration(migrations.Migration):
    dependencies = [('accounting','0039_staff_access')]
    operations = [migrations.RunSQL(FORWARD,REVERSE)]
