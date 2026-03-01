"""
Celery tasks for the voting application.

Handles heavy operations asynchronously:
- Bulk ballot processing
- Vote summary recalculation
- Cache warming
"""

import logging
from celery import shared_task
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.db.models import Count

logger = logging.getLogger('voting')


@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def process_bulk_ballots(self, election_id, rows, user_id):
    """
    Process bulk ballot import asynchronously.
    Used when the upload is very large and needs queue-based serialization.
    """
    from .models import Election, Candidate, Ballot, AuditLog, VoteSummary
    from accounts.models import User

    try:
        election = Election.objects.get(pk=election_id)
        user = User.objects.get(pk=user_id)
        candidate_map = dict(
            Candidate.objects.filter(election=election).values_list('code', 'pk')
        )

        chunk_size = getattr(settings, 'BALLOT_BULK_CHUNK_SIZE', 500)
        ballots = []
        for row in rows:
            bc = row['ballot_code'].strip().upper()
            cid = candidate_map.get(row.get('candidate_code', '').strip().upper())
            if cid:
                ballots.append(Ballot(
                    election=election,
                    candidate_id=cid,
                    ballot_code=bc,
                    entered_by=user,
                ))

        created = 0
        with transaction.atomic():
            for i in range(0, len(ballots), chunk_size):
                chunk = ballots[i:i + chunk_size]
                Ballot.objects.bulk_create(chunk, ignore_conflicts=False)
                created += len(chunk)

            # Rebuild summaries
            rebuild_vote_summaries(election_id)

            AuditLog.objects.create(
                election=election,
                action=AuditLog.Action.BULK_IMPORT,
                performed_by=user,
                after_data={'count': created, 'source': 'celery_task'},
                description=f'Async bulk imported {created} ballots.',
            )

        # Clear cache
        cache.delete(f'dashboard_{election_id}')
        logger.info(f'Bulk processed {created} ballots for election {election_id}')
        return {'status': 'success', 'created': created}

    except Exception as exc:
        logger.error(f'Bulk ballot processing failed: {exc}')
        raise self.retry(exc=exc)


@shared_task
def rebuild_vote_summaries(election_id):
    """Recalculate all VoteSummary records from actual ballot counts."""
    from django.db.models import Q
    from .models import Election, Ballot, VoteSummary

    election = Election.objects.get(pk=election_id)
    summaries = (
        Ballot.objects.filter(election=election)
        .values('candidate')
        .annotate(
            total=Count('id'),
            verified=Count('id', filter=Q(verification_status='VERIFIED')),
        )
    )

    with transaction.atomic():
        for row in summaries:
            VoteSummary.objects.update_or_create(
                election=election,
                candidate_id=row['candidate'],
                defaults={
                    'total_votes': row['total'],
                    'verified_votes': row['verified'],
                },
            )

    cache.delete(f'dashboard_{election_id}')
    logger.info(f'Vote summaries rebuilt for election {election_id}')


@shared_task
def warm_dashboard_cache(election_id):
    """Pre-compute and cache dashboard data."""
    from .views import DashboardView
    from .models import Election

    election = Election.objects.get(pk=election_id)
    # Force recalculate by deleting cache first
    cache.delete(f'dashboard_{election_id}')
    DashboardView._get_dashboard_data(election)
    logger.info(f'Dashboard cache warmed for election {election_id}')
