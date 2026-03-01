"""
Signals for automatic audit logging and vote summary updates.
"""
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.db.models import F

from .models import Ballot, AuditLog, VoteSummary


@receiver(post_save, sender=Ballot)
def ballot_post_save(sender, instance, created, **kwargs):
    """Update VoteSummary when a ballot is created or changed."""
    if created:
        summary, _ = VoteSummary.objects.get_or_create(
            election=instance.election,
            candidate=instance.candidate,
            defaults={'total_votes': 0, 'verified_votes': 0},
        )
        VoteSummary.objects.filter(pk=summary.pk).update(
            total_votes=F('total_votes') + 1
        )


@receiver(post_delete, sender=Ballot)
def ballot_post_delete(sender, instance, **kwargs):
    """Decrement VoteSummary when a ballot is deleted."""
    VoteSummary.objects.filter(
        election=instance.election,
        candidate=instance.candidate,
    ).update(total_votes=F('total_votes') - 1)
