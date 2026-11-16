"""Trusted operator CLI; staff service calls retain per-office authority."""
import json
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management.base import BaseCommand, CommandError
from accounting.job_services import cancel_job, enqueue_probe, jobs_for_user, queue_health, recover_jobs


class Command(BaseCommand):
    help = 'Κατάσταση και έλεγχος εργασιών παρασκηνίου.'

    def add_arguments(self, parser):
        sub = parser.add_subparsers(dest='action', required=True)
        health = sub.add_parser('health')
        health.add_argument('--strict', action='store_true')
        health.add_argument('--component', choices=['all', 'worker', 'scheduler'], default='all')
        sub.add_parser('dispatch')
        for name in ('list', 'enqueue-demo', 'cancel'):
            p = sub.add_parser(name)
            p.add_argument('--user-id', type=int, required=True)
            if name == 'enqueue-demo':
                p.add_argument('--entity-id', type=int, required=True)
                p.add_argument('--key', required=True)
                p.add_argument('--failures', type=int, default=0)
            if name == 'cancel':
                p.add_argument('--job-id', required=True)

    def handle(self, *args, **options):
        try:
            action = options['action']
            if action == 'health':
                result = queue_health()
                component = options['component']
                ok = result['status'] == 'ok' if component == 'all' else result[component]
                self.stdout.write(json.dumps(result, ensure_ascii=False))
                if options['strict'] and not ok:
                    raise CommandError('Η υπηρεσία εργασιών δεν είναι διαθέσιμη.')
                return
            if action == 'dispatch':
                self.stdout.write(json.dumps({'dispatched': recover_jobs()}))
                return
            user = get_user_model().objects.get(pk=options['user_id'])
            if action == 'enqueue-demo':
                job = enqueue_probe(user, entity_id=options['entity_id'], key=options['key'], failures=options['failures'])
                result = {'job_id': str(job.pk), 'correlation_id': str(job.correlation_id), 'state': job.get_state_display()}
            elif action == 'cancel':
                job = cancel_job(user, options['job_id'])
                result = {'job_id': str(job.pk), 'state': job.get_state_display()}
            else:
                result = [{'job_id': str(j.pk), 'state': j.get_state_display(), 'attempts': j.attempts,
                    'code': j.last_code, 'correlation_id': str(j.correlation_id)} for j in jobs_for_user(user).order_by('-created_at')[:100]]
            self.stdout.write(json.dumps(result, ensure_ascii=False))
        except (PermissionDenied, ValidationError, get_user_model().DoesNotExist):
            raise CommandError('Η ενέργεια δεν επιτρέπεται ή τα στοιχεία δεν είναι έγκυρα.') from None
