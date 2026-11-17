"""Explicit office-bound preview, catch-up, enqueue and reconciliation."""
import json
import uuid
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import DatabaseError
from django.utils import timezone
from accounting.capabilities import require_capability
from accounting.fee_models import FeeSchedule
from accounting.fee_services import month, next_month
from accounting.fee_generation_services import enqueue_period, reconciliation
from accounting.job_services import execute_job


class Command(BaseCommand):
    help='Προεπισκόπηση και ελεγχόμενη δημιουργία μηνιαίων χρεώσεων χωρίς είσπραξη.'

    def add_arguments(self,parser):
        parser.add_argument('action',choices=['preview','enqueue','run','reconcile'],nargs='?',default='preview')
        parser.add_argument('--user-id',type=int,required=True,help='Ενεργός λογιστής που αναλαμβάνει την ενέργεια.')
        parser.add_argument('--office-id',type=int,required=True,help='Ρητή επιβεβαίωση γραφείου· ελέγχεται έναντι του προφίλ.')
        parser.add_argument('--start-period',help='Πρώτος μήνας ΕΕΕΕ-ΜΜ. Προεπιλογή ο τρέχων μήνας Αθήνας.')
        parser.add_argument('--months',type=int,default=1,help='Από 1 έως 24 μήνες αναπλήρωσης.')
        parser.add_argument('--schedule',help='Προαιρετικό συγκεκριμένο πρόγραμμα UUID.')
        parser.add_argument('--request-key',help='Σταθερό UUID επανάληψης του ρητού αιτήματος.')
        parser.add_argument('--reason',help='Αιτιολογία ελέγχου περιόδων και ποσών.')
        parser.add_argument('--dry-run',action='store_true',help='Μόνο προεπισκόπηση, ακόμη και με run ή enqueue.')

    def handle(self,*args,**options):
        try:
            user=get_user_model().objects.get(pk=options['user_id'])
            writing=options['action'] in {'enqueue','run'} and not options['dry_run']
            profile=require_capability(user,'finance.write' if writing else 'finance.read')
            if profile.office_id!=options['office_id']:raise PermissionDenied('Το γραφείο δεν αντιστοιχεί στο ενεργό προφίλ.')
            if not 1<=options['months']<=24:raise ValidationError('Επιλέξτε 1–24 μήνες.')
            first=month(options['start_period']) if options['start_period'] else timezone.localdate().replace(day=1)
            periods=[];period=first
            for _ in range(options['months']):periods.append(period);period=next_month(period)
            ids=FeeSchedule.objects.filter(office_id=profile.office_id).order_by('pk')
            if options['schedule']:ids=ids.filter(pk=uuid.UUID(options['schedule']))
            keys=list(ids.values_list('pk',flat=True)[:101])
            if len(keys)>100:raise ValidationError('Περιορίστε την εκτέλεση με --schedule: έως 100 προγράμματα ανά αίτημα.')
            if options['schedule'] and not keys:raise PermissionDenied('Το πρόγραμμα δεν είναι διαθέσιμο στο γραφείο.')
            jobs=[]
            if writing:
                if not options['reason'] or not options['request_key']:raise ValidationError('Απαιτούνται --request-key και --reason μετά τον έλεγχο προεπισκόπησης.')
                request=uuid.UUID(options['request_key'])
                if periods[-1]>timezone.localdate().replace(day=1):raise ValidationError('Η αναπλήρωση δεν περιλαμβάνει μελλοντικό μήνα.')
                for period in periods:
                    for key in keys:
                        job=enqueue_period(user,schedule_id=key,period=period,request_key=request,reason=options['reason'])
                        jobs.append(str(job.pk))
                        if options['action']=='run':execute_job(job.pk)
            results=[reconciliation(user,period=p,schedule_id=options['schedule']) for p in periods]
            self.stdout.write(json.dumps({'action':options['action'],'dry_run':not writing,'jobs':jobs,'periods':results},
                cls=DjangoJSONEncoder,ensure_ascii=False))
        except (get_user_model().DoesNotExist,PermissionDenied,ValidationError,ValueError,TypeError) as error:
            raise CommandError(' '.join(error.messages) if isinstance(error,ValidationError) else str(error)) from None
        except DatabaseError:
            raise CommandError('Η καταχώριση δεν ολοκληρώθηκε. Ελέγξτε την κατάσταση και επαναλάβετε με το ίδιο αναγνωριστικό.') from None
