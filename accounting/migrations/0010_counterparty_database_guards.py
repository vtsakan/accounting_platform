"""Normalised AFM, immutable identity/history and archive/new-work serialization."""
from django.db import migrations


SPACE_POINTS = [32,9,13,10,11,12,133,160,5760,8192,8193,8194,8195,8196,8197,8198,8199,8200,8201,8202,8232,8233,8239,8287,12288]
REMOVED = " || ".join(f"chr({number})" for number in SPACE_POINTS)
FORWARD = """
CREATE FUNCTION accounting_s15_afm_key(value text) RETURNS text LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE key text;
BEGIN
 key := upper(translate(coalesce(value,''), '０１２３４５６７８９' || """ + REMOVED + """ || '-', '0123456789'));
 IF key='EL' THEN
   RAISE EXCEPTION 'Invalid counterparty AFM syntax' USING ERRCODE='23514',CONSTRAINT='entity_afm_syntax';
 END IF;
 IF left(key,2)='EL' THEN key:=substr(key,3); END IF;
 IF key<>'' AND key !~ '^[0-9]{9}$' THEN
   RAISE EXCEPTION 'Invalid counterparty AFM syntax' USING ERRCODE='23514',CONSTRAINT='entity_afm_syntax';
 END IF;
 RETURN key;
END $$;

CREATE FUNCTION accounting_s15_entity_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='DELETE' THEN
   RAISE EXCEPTION 'Archive counterparties; retain their identity and history' USING ERRCODE='23514',CONSTRAINT='entity_history_preserved';
 END IF;
 NEW.vat_key:=accounting_s15_afm_key(NEW.vat_number);
 IF TG_OP='UPDATE' THEN
   IF NEW.entity_type IS DISTINCT FROM OLD.entity_type THEN
     RAISE EXCEPTION 'Legacy counterparty mapping is immutable' USING ERRCODE='23514',CONSTRAINT='entity_legacy_type_immutable';
   END IF;
   NEW.record_version:=OLD.record_version+1;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER s15_entity_guard BEFORE INSERT OR UPDATE OR DELETE ON accounting_entity
 FOR EACH ROW EXECUTE FUNCTION accounting_s15_entity_guard();

CREATE FUNCTION accounting_s15_active_links() RETURNS trigger LANGUAGE plpgsql VOLATILE AS $$
DECLARE ids bigint[]; item record; agreement_entity bigint;
BEGIN
 -- Match the office-before-entity order used by archive/revocation services.
 -- Acquire this FK-compatible lock before holding an entity row through commit.
 PERFORM id FROM accounting_office WHERE id=NEW.office_id FOR KEY SHARE;
 IF TG_TABLE_NAME='accounting_agreement' THEN
   IF TG_OP='UPDATE' THEN
     IF NEW.entity_id IS NOT DISTINCT FROM OLD.entity_id THEN RETURN NEW; END IF;
   END IF;
   ids:=ARRAY[NEW.entity_id];
 ELSE
   IF TG_OP='UPDATE' THEN
     IF NEW.entity_id IS NOT DISTINCT FROM OLD.entity_id AND NEW.agreement_id IS NOT DISTINCT FROM OLD.agreement_id THEN RETURN NEW; END IF;
   END IF;
   SELECT entity_id INTO agreement_entity FROM accounting_agreement WHERE id=NEW.agreement_id AND office_id=NEW.office_id;
   ids:=ARRAY[NEW.entity_id,agreement_entity];
 END IF;
 FOR item IN SELECT id,is_archived FROM accounting_entity WHERE id=ANY(ids) AND office_id=NEW.office_id ORDER BY id FOR UPDATE LOOP
   IF item.is_archived THEN
     RAISE EXCEPTION 'Restore archived counterparty before new work' USING ERRCODE='23514',CONSTRAINT='s15_archived_work';
   END IF;
 END LOOP;
 RETURN NEW;
END $$;
CREATE TRIGGER s15_agreement_active BEFORE INSERT OR UPDATE OF entity_id ON accounting_agreement
 FOR EACH ROW EXECUTE FUNCTION accounting_s15_active_links();
CREATE TRIGGER s15_transaction_active BEFORE INSERT OR UPDATE OF entity_id,agreement_id ON accounting_transaction
 FOR EACH ROW EXECUTE FUNCTION accounting_s15_active_links();

CREATE FUNCTION accounting_s15_event_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 RAISE EXCEPTION 'Counterparty events are append only' USING ERRCODE='23514',CONSTRAINT='counterparty_event_immutable';
END $$;
CREATE TRIGGER s15_event_guard BEFORE UPDATE OR DELETE ON accounting_counterpartyevent
 FOR EACH ROW EXECUTE FUNCTION accounting_s15_event_guard();

ALTER TABLE accounting_counterpartyevent ADD CONSTRAINT counterparty_event_same_office
 FOREIGN KEY (entity_id,office_id) REFERENCES accounting_entity(id,office_id) DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE accounting_counterpartyevent ADD CONSTRAINT counterparty_actor_same_office
 FOREIGN KEY (actor_id,office_id) REFERENCES accounting_accountantprofile(user_id,office_id) DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE accounting_entity ADD CONSTRAINT counterparty_archiver_same_office
 FOREIGN KEY (archived_by_id,office_id) REFERENCES accounting_accountantprofile(user_id,office_id) DEFERRABLE INITIALLY IMMEDIATE;
"""

REVERSE = """
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM accounting_counterpartyevent) OR
    EXISTS(SELECT 1 FROM accounting_entity WHERE (is_customer AND is_supplier) OR is_archived OR legal_kind<>'UNREVIEWED') THEN
   RAISE EXCEPTION 'S15 downgrade needs a reviewed identity/history preservation plan';
 END IF;
END $$;
ALTER TABLE accounting_entity DROP CONSTRAINT counterparty_archiver_same_office;
ALTER TABLE accounting_counterpartyevent DROP CONSTRAINT counterparty_actor_same_office;
ALTER TABLE accounting_counterpartyevent DROP CONSTRAINT counterparty_event_same_office;
DROP TRIGGER s15_event_guard ON accounting_counterpartyevent;
DROP FUNCTION accounting_s15_event_guard();
DROP TRIGGER s15_transaction_active ON accounting_transaction;
DROP TRIGGER s15_agreement_active ON accounting_agreement;
DROP FUNCTION accounting_s15_active_links();
DROP TRIGGER s15_entity_guard ON accounting_entity;
DROP FUNCTION accounting_s15_entity_guard();
DROP FUNCTION accounting_s15_afm_key(text);
"""


class Migration(migrations.Migration):
    dependencies = [('accounting','0009_counterparty_workspace')]
    operations = [migrations.RunSQL(FORWARD, REVERSE)]
