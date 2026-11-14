"""Same-office workflow links, immutable audit and last-active-owner protection.

VOLATILE trigger queries take a fresh READ COMMITTED snapshot after the office
lock. Existing ownerless legacy offices are not assigned an invented owner.
"""
from django.db import migrations

FORWARD = """
CREATE FUNCTION accounting_s14_guard_profile() RETURNS trigger LANGUAGE plpgsql VOLATILE AS $$
BEGIN
  IF TG_OP = 'UPDATE' AND (NEW.user_id IS DISTINCT FROM OLD.user_id OR NEW.office_id IS DISTINCT FROM OLD.office_id) THEN
    RAISE EXCEPTION 'Membership identity is immutable' USING ERRCODE='23514', CONSTRAINT='membership_identity_immutable';
  END IF;
  IF OLD.role = 'owner' AND OLD.is_active AND
     (TG_OP = 'DELETE' OR NEW.role <> 'owner' OR NOT NEW.is_active) THEN
    PERFORM id FROM accounting_office WHERE id=OLD.office_id FOR UPDATE;
    IF EXISTS (SELECT 1 FROM accounting_office o JOIN auth_user u ON u.id=OLD.user_id
               WHERE o.id=OLD.office_id AND o.is_active AND u.is_active) AND
       NOT EXISTS (SELECT 1 FROM accounting_accountantprofile p JOIN auth_user u ON u.id=p.user_id
                   WHERE p.office_id=OLD.office_id AND p.id<>OLD.id AND p.role='owner' AND p.is_active AND u.is_active) THEN
      RAISE EXCEPTION 'Office needs an active owner' USING ERRCODE='23514', CONSTRAINT='office_requires_active_owner';
    END IF;
  END IF;
  IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER accounting_s14_profile_guard BEFORE UPDATE OR DELETE ON accounting_accountantprofile
 FOR EACH ROW EXECUTE FUNCTION accounting_s14_guard_profile();

CREATE FUNCTION accounting_s14_guard_user() RETURNS trigger LANGUAGE plpgsql VOLATILE AS $$
DECLARE scope uuid;
BEGIN
  IF OLD.is_active AND (TG_OP='DELETE' OR NOT NEW.is_active) THEN
    SELECT office_id INTO scope FROM accounting_accountantprofile WHERE user_id=OLD.id AND role='owner' AND is_active;
    IF scope IS NOT NULL THEN
      PERFORM id FROM accounting_office WHERE id=scope FOR UPDATE;
      IF EXISTS(SELECT 1 FROM accounting_office WHERE id=scope AND is_active) AND
         NOT EXISTS(SELECT 1 FROM accounting_accountantprofile p JOIN auth_user u ON u.id=p.user_id
                     WHERE p.office_id=scope AND p.user_id<>OLD.id AND p.role='owner' AND p.is_active AND u.is_active) THEN
        RAISE EXCEPTION 'Office needs an active owner' USING ERRCODE='23514', CONSTRAINT='office_requires_active_owner';
      END IF;
    END IF;
  END IF;
  IF TG_OP='DELETE' THEN RETURN OLD; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER accounting_s14_user_guard BEFORE UPDATE OF is_active OR DELETE ON auth_user
 FOR EACH ROW EXECUTE FUNCTION accounting_s14_guard_user();

CREATE FUNCTION accounting_s14_guard_audit() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 RAISE EXCEPTION 'Office audit events are append only' USING ERRCODE='23514', CONSTRAINT='office_audit_immutable';
END $$;
CREATE TRIGGER accounting_s14_audit_guard BEFORE UPDATE OR DELETE ON accounting_officeauditevent
 FOR EACH ROW EXECUTE FUNCTION accounting_s14_guard_audit();
"""

LINKS = [("accounting_staffinvitation", "invited_by_id", "staff_inviter_same_office"),
         ("accounting_staffinvitation", "accepted_by_id", "staff_recipient_same_office"),
         ("accounting_ownershiphandover", "requested_by_id", "handover_source_same_office"),
         ("accounting_ownershiphandover", "recipient_id", "handover_target_same_office"),
         ("accounting_officeauditevent", "actor_id", "audit_actor_same_office"),
         ("accounting_officeauditevent", "target_user_id", "audit_target_same_office")]

for table, column, name in LINKS:
    FORWARD += (f"ALTER TABLE {table} ADD CONSTRAINT {name} FOREIGN KEY ({column},office_id) "
                "REFERENCES accounting_accountantprofile(user_id,office_id) DEFERRABLE INITIALLY IMMEDIATE;\n")

REVERSE = "".join(f"ALTER TABLE {table} DROP CONSTRAINT {name};\n" for table, _, name in reversed(LINKS)) + """
DROP TRIGGER accounting_s14_audit_guard ON accounting_officeauditevent;
DROP FUNCTION accounting_s14_guard_audit();
DROP TRIGGER accounting_s14_user_guard ON auth_user;
DROP FUNCTION accounting_s14_guard_user();
DROP TRIGGER accounting_s14_profile_guard ON accounting_accountantprofile;
DROP FUNCTION accounting_s14_guard_profile();
"""


class Migration(migrations.Migration):
    dependencies = [("accounting", "0007_office_settings_staff_workflows")]
    operations = [migrations.RunSQL(FORWARD, REVERSE)]
