"""Synthetic S27 route records for the unchanged boundary assertions."""
from django.utils import timezone


def seed_fee_routes(fixture):
    from .models import Agreement
    from .charge_services import save_terms
    from .fee_services import create_schedule, save_price
    day = timezone.localdate()
    for suffix in ('a', 'b'):
        actor = fixture.owner if suffix == 'a' else fixture.owner_b
        entity = getattr(fixture, 'entity_' + suffix)
        agreement = Agreement(entity=entity, agreement_type='RECEIVABLE', description='ΔΟΚΙΜΗ ΜΗΝΙΑΙΑΣ ΑΜΟΙΒΗΣ ' + suffix,
            total_amount='100.00', start_date=day.replace(day=1))
        save_terms(actor, agreement, billing_mode='MONTHLY', lifecycle='ACTIVE', reason='Συνθετικοί μηνιαίοι όροι S27')
        price = save_price(actor, code='S27-' + suffix.upper(), description='ΔΟΚΙΜΗ ΥΠΗΡΕΣΙΑΣ ' + suffix,
            amount='100.00', effective_date=day, reason='Συνθετικός τιμοκατάλογος S27')
        schedule = create_schedule(actor, agreement_id=agreement.pk, start_period=day.replace(day=1),
            reason='Συνθετικό πρόγραμμα για έλεγχο ορίων S27')
        setattr(fixture, 'service_' + suffix, price.service)
        setattr(fixture, 'fee_' + suffix, schedule)
