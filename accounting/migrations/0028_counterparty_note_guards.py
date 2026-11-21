"""Same-office history, server attribution/time and append-only note rows."""
from django.db import migrations

FORWARD = r"""
ALTER TABLE accounting_counterpartynote ADD CONSTRAINT cr004_note_entity_office
 FOREIGN KEY (entity_id,office_id) REFERENCES accounting_entity(id,office_id) DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE accounting_counterpartynote ADD CONSTRAINT cr004_note_actor_office
 FOREIGN KEY (actor_id,office_id) REFERENCES accounting_accountantprofile(user_id,office_id) DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE accounting_counterpartynote ADD CONSTRAINT cr004_note_length
 CHECK (char_length(body) BETWEEN 1 AND 5000);

CREATE FUNCTION accounting_cr004_note_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE actor_name text; archived boolean;
BEGIN
 IF TG_OP<>'INSERT' THEN
  RAISE EXCEPTION 'Notes are retained; append a new note for corrections'
   USING ERRCODE='23514',CONSTRAINT='cr004_note_immutable';
 END IF;
 PERFORM id FROM accounting_office WHERE id=NEW.office_id AND is_active FOR KEY SHARE;
 IF NOT FOUND THEN
  RAISE EXCEPTION 'An active office is required' USING ERRCODE='23514',CONSTRAINT='cr004_note_authority';
 END IF;
 SELECT username INTO actor_name FROM auth_user WHERE id=NEW.actor_id AND is_active FOR KEY SHARE;
 IF NOT FOUND THEN
  RAISE EXCEPTION 'An active accountant is required' USING ERRCODE='23514',CONSTRAINT='cr004_note_authority';
 END IF;
 PERFORM id FROM accounting_accountantprofile WHERE user_id=NEW.actor_id AND office_id=NEW.office_id
  AND is_active AND role IN ('owner','accountant') FOR KEY SHARE;
 IF NOT FOUND THEN
  RAISE EXCEPTION 'Accountant must belong to this office' USING ERRCODE='23514',CONSTRAINT='cr004_note_authority';
 END IF;
 SELECT is_archived INTO archived FROM accounting_entity
  WHERE id=NEW.entity_id AND office_id=NEW.office_id FOR UPDATE;
 IF NOT FOUND OR archived THEN
  RAISE EXCEPTION 'Restore the same-office counterparty before new work'
   USING ERRCODE='23514',CONSTRAINT='cr004_note_entity_active';
 END IF;
 NEW.actor_label:=actor_name;
 NEW.created_at:=clock_timestamp();
 RETURN NEW;
END $$;
CREATE TRIGGER cr004_note_guard BEFORE INSERT OR UPDATE OR DELETE ON accounting_counterpartynote
 FOR EACH ROW EXECUTE FUNCTION accounting_cr004_note_guard();
"""

REVERSE = r"""
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM accounting_counterpartynote) THEN
  RAISE EXCEPTION 'Retain note history before any reviewed downgrade';
 END IF;
END $$;
DROP TRIGGER cr004_note_guard ON accounting_counterpartynote;
DROP FUNCTION accounting_cr004_note_guard();
ALTER TABLE accounting_counterpartynote DROP CONSTRAINT cr004_note_length;
ALTER TABLE accounting_counterpartynote DROP CONSTRAINT cr004_note_actor_office;
ALTER TABLE accounting_counterpartynote DROP CONSTRAINT cr004_note_entity_office;
"""


class Migration(migrations.Migration):
    dependencies = [('accounting', '0027_counterparty_notes')]
    operations = [migrations.RunSQL(FORWARD, REVERSE)]
