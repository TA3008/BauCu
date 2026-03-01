"""
Management command to seed the database with sample data for development.
Creates users, an election, candidates, and sample ballots.
"""

import random
import string
from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import User
from voting.models import Election, Candidate, Ballot, VoteSummary, AuditLog


class Command(BaseCommand):
    help = 'Seed database with sample election data for development'

    def add_arguments(self, parser):
        parser.add_argument(
            '--ballots', type=int, default=100,
            help='Number of sample ballots to create (default: 100)',
        )

    def handle(self, *args, **options):
        num_ballots = options['ballots']
        self.stdout.write('Seeding database...\n')

        with transaction.atomic():
            # Create users
            admin_user, _ = User.objects.get_or_create(
                username='admin',
                defaults={
                    'role': User.Role.ADMIN,
                    'is_staff': True,
                    'is_superuser': True,
                    'email': 'admin@baucu.local',
                },
            )
            admin_user.set_password('admin123')
            admin_user.save()

            operator1, _ = User.objects.get_or_create(
                username='operator1',
                defaults={
                    'role': User.Role.OPERATOR,
                    'email': 'op1@baucu.local',
                },
            )
            operator1.set_password('operator123')
            operator1.save()

            operator2, _ = User.objects.get_or_create(
                username='operator2',
                defaults={
                    'role': User.Role.OPERATOR,
                    'email': 'op2@baucu.local',
                },
            )
            operator2.set_password('operator123')
            operator2.save()

            viewer, _ = User.objects.get_or_create(
                username='viewer',
                defaults={
                    'role': User.Role.VIEWER,
                    'email': 'viewer@baucu.local',
                },
            )
            viewer.set_password('viewer123')
            viewer.save()

            self.stdout.write(self.style.SUCCESS(
                'Users created: admin/admin123, operator1/operator123, '
                'operator2/operator123, viewer/viewer123'
            ))

            # Create election
            election, created = Election.objects.get_or_create(
                name='Sample Election 2026',
                defaults={
                    'description': 'A sample election for testing the BauCu voting system.',
                    'status': Election.Status.OPEN,
                    'created_by': admin_user,
                },
            )
            if not created:
                self.stdout.write('Election already exists, skipping candidate/ballot creation.')
                return

            # Create candidates
            candidates_data = [
                ('C01', 'Nguyen Van A', 1),
                ('C02', 'Tran Thi B', 2),
                ('C03', 'Le Van C', 3),
                ('C04', 'Pham Thi D', 4),
                ('C05', 'Hoang Van E', 5),
            ]
            candidates = []
            for code, name, order in candidates_data:
                c = Candidate.objects.create(
                    election=election, code=code, name=name, order=order,
                )
                candidates.append(c)
                VoteSummary.objects.create(
                    election=election, candidate=c,
                    total_votes=0, verified_votes=0,
                )

            self.stdout.write(self.style.SUCCESS(
                f'Election "{election.name}" created with {len(candidates)} candidates.'
            ))

            # Create sample ballots
            operators = [operator1, operator2]
            ballots = []
            for i in range(num_ballots):
                code = f'BLT-{i+1:05d}'
                candidate = random.choice(candidates)
                entered_by = random.choice(operators)
                ballots.append(Ballot(
                    election=election,
                    candidate=candidate,
                    ballot_code=code,
                    entered_by=entered_by,
                ))

            Ballot.objects.bulk_create(ballots)

            # Update summaries
            from django.db.models import Count
            for row in (
                Ballot.objects.filter(election=election)
                .values('candidate')
                .annotate(cnt=Count('id'))
            ):
                VoteSummary.objects.filter(
                    election=election, candidate_id=row['candidate']
                ).update(total_votes=row['cnt'])

            # Verify some ballots
            pending = list(
                Ballot.objects.filter(
                    election=election,
                    verification_status=Ballot.VerificationStatus.PENDING,
                )[:num_ballots // 2]
            )
            for ballot in pending:
                verifier = operator2 if ballot.entered_by == operator1 else operator1
                ballot.verification_status = Ballot.VerificationStatus.VERIFIED
                ballot.verified_by = verifier
                ballot.save(update_fields=['verification_status', 'verified_by', 'updated_at'])

            # Update verified counts
            from django.db.models import Q
            for row in (
                Ballot.objects.filter(
                    election=election,
                    verification_status=Ballot.VerificationStatus.VERIFIED,
                )
                .values('candidate')
                .annotate(cnt=Count('id'))
            ):
                VoteSummary.objects.filter(
                    election=election, candidate_id=row['candidate']
                ).update(verified_votes=row['cnt'])

            AuditLog.objects.create(
                election=election,
                action=AuditLog.Action.BULK_IMPORT,
                performed_by=admin_user,
                after_data={'count': num_ballots, 'source': 'seed_command'},
                description=f'Seeded {num_ballots} sample ballots.',
            )

            self.stdout.write(self.style.SUCCESS(
                f'{num_ballots} ballots created, ~{len(pending)} verified.'
            ))
            self.stdout.write(self.style.SUCCESS('Database seeding complete!'))
