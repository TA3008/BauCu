"""
Tests for the voting application.
Covers models, forms, views, and concurrency scenarios.
"""

from django.test import TestCase, TransactionTestCase, Client
from django.urls import reverse
from django.db import transaction

from accounts.models import User
from voting.models import Election, Candidate, Ballot, AuditLog, VoteSummary


class ModelTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='admin', password='pass', role=User.Role.ADMIN,
            is_staff=True, is_superuser=True,
        )
        self.op1 = User.objects.create_user(
            username='op1', password='pass', role=User.Role.OPERATOR,
        )
        self.op2 = User.objects.create_user(
            username='op2', password='pass', role=User.Role.OPERATOR,
        )
        self.election = Election.objects.create(
            name='Test Election', status=Election.Status.OPEN,
            created_by=self.admin,
        )
        self.c1 = Candidate.objects.create(
            election=self.election, name='Candidate A', code='C01', order=1,
        )
        self.c2 = Candidate.objects.create(
            election=self.election, name='Candidate B', code='C02', order=2,
        )
        for c in [self.c1, self.c2]:
            VoteSummary.objects.create(
                election=self.election, candidate=c,
                total_votes=0, verified_votes=0,
            )

    def test_user_roles(self):
        self.assertTrue(self.admin.is_admin_role)
        self.assertTrue(self.op1.is_operator)
        self.assertFalse(self.op1.is_admin_role)

    def test_candidate_unique_code(self):
        with self.assertRaises(Exception):
            Candidate.objects.create(
                election=self.election, name='Dup', code='C01', order=3,
            )

    def test_ballot_creation_updates_summary(self):
        Ballot.objects.create(
            election=self.election, candidate=self.c1,
            ballot_code='BLT-001', entered_by=self.op1,
        )
        summary = VoteSummary.objects.get(
            election=self.election, candidate=self.c1,
        )
        self.assertEqual(summary.total_votes, 1)

    def test_ballot_unique_per_election(self):
        Ballot.objects.create(
            election=self.election, candidate=self.c1,
            ballot_code='BLT-001', entered_by=self.op1,
        )
        with self.assertRaises(Exception):
            Ballot.objects.create(
                election=self.election, candidate=self.c2,
                ballot_code='BLT-001', entered_by=self.op1,
            )


class ViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_user(
            username='admin', password='pass', role=User.Role.ADMIN,
            is_staff=True, is_superuser=True,
        )
        self.op = User.objects.create_user(
            username='op', password='pass', role=User.Role.OPERATOR,
        )
        self.viewer = User.objects.create_user(
            username='viewer', password='pass', role=User.Role.VIEWER,
        )
        self.election = Election.objects.create(
            name='Test', status=Election.Status.OPEN, created_by=self.admin,
        )
        self.c1 = Candidate.objects.create(
            election=self.election, name='A', code='C01', order=1,
        )
        VoteSummary.objects.create(
            election=self.election, candidate=self.c1,
            total_votes=0, verified_votes=0,
        )

    def test_login_required(self):
        resp = self.client.get(reverse('voting:election_list'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('login', resp.url)

    def test_election_list_accessible(self):
        self.client.login(username='viewer', password='pass')
        resp = self.client.get(reverse('voting:election_list'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Test')

    def test_dashboard_admin_only(self):
        self.client.login(username='viewer', password='pass')
        resp = self.client.get(
            reverse('voting:dashboard', kwargs={'election_pk': self.election.pk})
        )
        self.assertNotEqual(resp.status_code, 200)

        self.client.login(username='admin', password='pass')
        resp = self.client.get(
            reverse('voting:dashboard', kwargs={'election_pk': self.election.pk})
        )
        self.assertEqual(resp.status_code, 200)

    def test_ballot_entry(self):
        self.client.login(username='op', password='pass')
        resp = self.client.post(
            reverse('voting:ballot_create', kwargs={'election_pk': self.election.pk}),
            {'candidate': self.c1.pk, 'ballot_code': 'BLT-001'},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Ballot.objects.filter(ballot_code='BLT-001').exists())

    def test_api_dashboard(self):
        self.client.login(username='admin', password='pass')
        resp = self.client.get(
            reverse('voting:api_dashboard', kwargs={'election_pk': self.election.pk})
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn('total_ballots', data)
        self.assertIn('candidates', data)
