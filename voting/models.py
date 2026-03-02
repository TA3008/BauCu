"""
Voting system models.

Design goals:
- Full audit trail on every mutation.
- Double-entry verification: two operators must confirm before finalization.
- Row-level locking via select_for_update() during critical writes.
- Indexed on candidate / ballot for fast aggregation queries.
"""

import uuid
from django.conf import settings
from django.db import models
from django.utils import timezone



# ---------------------------------------------------------------------------
# Election
# ---------------------------------------------------------------------------
class Election(models.Model):
    """A single election event containing candidates and ballots."""

    class Status(models.TextChoices):
        DRAFT = 'DRAFT', 'Draft'
        OPEN = 'OPEN', 'Open for Voting'
        CLOSED = 'CLOSED', 'Closed'
        ARCHIVED = 'ARCHIVED', 'Archived'

    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    # Validation rules for number of choices per ballot
    min_choices = models.PositiveIntegerField(null=True, blank=True, help_text='Minimum number of choices required for a valid ballot')
    max_choices = models.PositiveIntegerField(null=True, blank=True, help_text='Maximum number of choices allowed for a valid ballot')
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.DRAFT, db_index=True
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='elections_created'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'voting_election'
        ordering = ['-created_at']

    def __str__(self):
        return self.name


# ---------------------------------------------------------------------------
# Candidate
# ---------------------------------------------------------------------------
class Candidate(models.Model):
    """A candidate within an election."""

    election = models.ForeignKey(
        Election, on_delete=models.CASCADE, related_name='candidates'
    )
    name = models.CharField(max_length=255)
    # removed `code` field (not needed)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = 'voting_candidate'
        ordering = ['order', 'name']
        # no unique_together on code (field removed)
        indexes = []

    def __str__(self):
        return f'{self.name}'


# ---------------------------------------------------------------------------
# Ballot
# ---------------------------------------------------------------------------
class Ballot(models.Model):
    """
    A single ballot submitted by an operator.
    Uses UUID as external reference to avoid sequential ID leaks.
    """

    class VerificationStatus(models.TextChoices):
        PENDING = 'PENDING', 'Pending Verification'
        VERIFIED = 'VERIFIED', 'Verified'
        REJECTED = 'REJECTED', 'Rejected'

    id = models.BigAutoField(primary_key=True)
    ref = models.UUIDField(default=uuid.uuid4, unique=True, editable=False, db_index=True)
    election = models.ForeignKey(
        Election, on_delete=models.CASCADE, related_name='ballots'
    )
    candidate = models.ForeignKey(
        Candidate, on_delete=models.PROTECT, related_name='ballots', db_index=True,
        null=True, blank=True,
    )
    ballot_code = models.CharField(
        max_length=50,
        help_text='Unique ballot identifier printed on the paper ballot.',
    )

    # Double-entry verification
    entered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='ballots_entered',
    )
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='ballots_verified',
    )
    verification_status = models.CharField(
        max_length=10,
        choices=VerificationStatus.choices,
        default=VerificationStatus.PENDING,
        db_index=True,
    )

    # Mark ballots that violate election rules (kept for audit/listing but excluded from statistics)
    is_invalid = models.BooleanField(default=False, db_index=True)

    # Optimistic concurrency control field
    version = models.PositiveIntegerField(default=1)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'voting_ballot'
        ordering = ['-created_at']
        unique_together = [('election', 'ballot_code')]
        indexes = [
            models.Index(fields=['election', 'candidate'], name='idx_ballot_election_cand'),
            models.Index(fields=['election', 'verification_status'], name='idx_ballot_election_vstatus'),
            models.Index(fields=['entered_by'], name='idx_ballot_entered_by'),
        ]

    def __str__(self):
        cand = self.candidate.name if self.candidate else 'MULTI'
        return f'Ballot {self.ballot_code} → {cand}'



class BallotChoice(models.Model):
    """Associates a Ballot with a Candidate for multi-select ballots."""
    ballot = models.ForeignKey('Ballot', on_delete=models.CASCADE, related_name='choices')
    candidate = models.ForeignKey(Candidate, on_delete=models.PROTECT, related_name='ballot_choices')

    class Meta:
        db_table = 'voting_ballot_choice'
        unique_together = [('ballot', 'candidate')]

    def __str__(self):
        return f'{self.ballot.ballot_code} -> {self.candidate.name}'


# candidate code generation removed (field `code` was removed)


# ---------------------------------------------------------------------------
# Audit Log – immutable append-only log
# ---------------------------------------------------------------------------
class AuditLog(models.Model):
    """
    Immutable record of every data change.
    Stores before/after JSON snapshots plus metadata.
    """

    class Action(models.TextChoices):
        CREATE = 'CREATE', 'Created'
        UPDATE = 'UPDATE', 'Updated'
        DELETE = 'DELETE', 'Deleted'
        VERIFY = 'VERIFY', 'Verified'
        REJECT = 'REJECT', 'Rejected'
        BULK_IMPORT = 'BULK_IMPORT', 'Bulk Imported'

    id = models.BigAutoField(primary_key=True)
    election = models.ForeignKey(
        Election, on_delete=models.CASCADE, related_name='audit_logs'
    )
    ballot = models.ForeignKey(
        Ballot, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='audit_logs'
    )
    action = models.CharField(max_length=15, choices=Action.choices, db_index=True)
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='audit_logs',
    )
    before_data = models.JSONField(null=True, blank=True)
    after_data = models.JSONField(null=True, blank=True)
    description = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    timestamp = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        db_table = 'voting_audit_log'
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['election', 'action'], name='idx_audit_election_action'),
            models.Index(fields=['performed_by', 'timestamp'], name='idx_audit_user_ts'),
        ]

    def __str__(self):
        return f'[{self.action}] {self.description[:80]}'


# ---------------------------------------------------------------------------
# Vote Summary – materialized aggregate cache
# ---------------------------------------------------------------------------
class VoteSummary(models.Model):
    """
    Cached vote counts per candidate, updated atomically.
    Avoids expensive COUNT(*) on every dashboard load.
    """

    election = models.ForeignKey(
        Election, on_delete=models.CASCADE, related_name='vote_summaries'
    )
    candidate = models.OneToOneField(
        Candidate, on_delete=models.CASCADE, related_name='vote_summary'
    )
    total_votes = models.PositiveIntegerField(default=0)
    verified_votes = models.PositiveIntegerField(default=0)
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'voting_vote_summary'
        unique_together = [('election', 'candidate')]
        indexes = [
            models.Index(fields=['election', 'total_votes'], name='idx_vsummary_election_total'),
        ]

    def __str__(self):
        return f'{self.candidate.name}: {self.total_votes} votes'
