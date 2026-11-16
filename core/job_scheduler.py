"""One scheduler for a PostgreSQL database, including overlapping releases.

The dedicated session owns the advisory lock for the entire process lifetime.
Connection loss stops scheduling; a reconnect never silently resumes ownership.
PersistentScheduler's file stores last-run state on the shared retained volume.
"""
import uuid
import psycopg
from celery.beat import PersistentScheduler
from django.conf import settings

SCHEDULER_LOCK = 260016112026


class SchedulerAlreadyRunning(RuntimeError):
    pass


class SchedulerLease:
    def __init__(self):
        db = settings.DATABASES['default']
        self.owner = uuid.uuid4()
        self.connection = psycopg.connect(dbname=db['NAME'], user=db['USER'], password=db['PASSWORD'],
            host=db['HOST'], port=db['PORT'], autocommit=True, connect_timeout=5,
            application_name='accounting-s26-scheduler', keepalives=1, keepalives_idle=10,
            keepalives_interval=5, keepalives_count=2)
        if not self.connection.execute('SELECT pg_try_advisory_lock(%s)', (SCHEDULER_LOCK,)).fetchone()[0]:
            self.connection.close()
            raise SchedulerAlreadyRunning('A scheduler already owns this database')

    def pulse(self):
        try:
            self.connection.execute('SELECT 1')
            self.connection.execute('''INSERT INTO accounting_backgroundpulse(service,owner,last_seen_at)
                VALUES ('scheduler',%s,clock_timestamp()) ON CONFLICT(service)
                DO UPDATE SET owner=excluded.owner,last_seen_at=excluded.last_seen_at''', (self.owner,))
        except psycopg.Error:
            self.close()
            raise SystemExit('Scheduler database ownership lost') from None

    def close(self):
        self.connection.close()  # PostgreSQL atomically releases the session lock.


class SingletonScheduler(PersistentScheduler):
    def __init__(self, *args, **kwargs):
        # Metadata/banner inspection uses a lazy instance without ownership.
        self.lease = None if kwargs.get('lazy', False) else SchedulerLease()
        try:
            super().__init__(*args, **kwargs)
        except BaseException:
            if self.lease is not None:
                self.lease.close()
            raise

    def tick(self, *args, **kwargs):
        if self.lease is None:
            raise SystemExit('Scheduler has no database ownership')
        self.lease.pulse()
        return min(10, super().tick(*args, **kwargs))

    def close(self):
        try:
            super().close()
        finally:
            if self.lease is not None:
                self.lease.close()
