"""
Views for the voting application.

Covers:
- Election CRUD (admin)
- Single ballot entry (operator)
- Bulk ballot entry – CSV and paste (operator)
- Ballot verification (double-entry workflow)
- Admin dashboard with live percentages and audit log
- JSON API endpoints for AJAX / JS interactivity
"""

import json
import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.db import transaction
from django.db.models import Count, Q, F, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views import View
from django.views.decorators.http import require_POST
from django.views.generic import ListView, DetailView, CreateView, UpdateView

from .forms import (
    ElectionForm, CandidateFormSet, BallotForm,
    BulkBallotUploadForm, BulkBallotTextForm, BallotVerifyForm,
)
from .mixins import (
    AdminRequiredMixin, OperatorRequiredMixin, ViewerRequiredMixin, get_client_ip,
)
from .models import Election, Candidate, Ballot, AuditLog, VoteSummary, BallotChoice

logger = logging.getLogger('voting')

CACHE_TTL = 30  # seconds


# ===================================================================
# Election views
# ===================================================================
class ElectionListView(ViewerRequiredMixin, ListView):
    model = Election
    template_name = 'voting/election_list.html'
    context_object_name = 'elections'
    paginate_by = 20


class ElectionDetailView(ViewerRequiredMixin, DetailView):
    model = Election
    template_name = 'voting/election_detail.html'
    context_object_name = 'election'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        election = self.object
        ctx['candidates'] = election.candidates.all()
        ctx['total_ballots'] = election.ballots.count()
        ctx['pending_ballots'] = election.ballots.filter(
            verification_status=Ballot.VerificationStatus.PENDING
        ).count()
        return ctx


class ElectionCreateView(AdminRequiredMixin, CreateView):
    model = Election
    form_class = ElectionForm
    template_name = 'voting/election_form.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        if self.request.POST:
            ctx['candidate_formset'] = CandidateFormSet(self.request.POST)
        else:
            ctx['candidate_formset'] = CandidateFormSet()
        ctx['title'] = 'Create Election'
        return ctx

    def form_valid(self, form):
        ctx = self.get_context_data()
        formset = ctx['candidate_formset']
        if formset.is_valid():
            with transaction.atomic():
                form.instance.created_by = self.request.user
                self.object = form.save()
                formset.instance = self.object
                formset.save()
                # Initialize vote summaries for each candidate
                for candidate in self.object.candidates.all():
                    VoteSummary.objects.get_or_create(
                        election=self.object,
                        candidate=candidate,
                        defaults={'total_votes': 0, 'verified_votes': 0},
                    )
                AuditLog.objects.create(
                    election=self.object,
                    action=AuditLog.Action.CREATE,
                    performed_by=self.request.user,
                    after_data={'election': self.object.name},
                    description=f'Election "{self.object.name}" created.',
                    ip_address=get_client_ip(self.request),
                )
            messages.success(self.request, f'Election "{self.object.name}" created.')
            return redirect('voting:election_detail', pk=self.object.pk)
        else:
            return self.render_to_response(self.get_context_data(form=form))


class ElectionUpdateView(AdminRequiredMixin, UpdateView):
    model = Election
    form_class = ElectionForm
    template_name = 'voting/election_form.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        if self.request.POST:
            ctx['candidate_formset'] = CandidateFormSet(
                self.request.POST, instance=self.object
            )
        else:
            ctx['candidate_formset'] = CandidateFormSet(instance=self.object)
        ctx['title'] = f'Edit Election: {self.object.name}'
        return ctx

    def form_valid(self, form):
        ctx = self.get_context_data()
        formset = ctx['candidate_formset']
        if formset.is_valid():
            with transaction.atomic():
                self.object = form.save()
                formset.save()
                # Ensure summaries exist for any new candidates
                for candidate in self.object.candidates.all():
                    VoteSummary.objects.get_or_create(
                        election=self.object,
                        candidate=candidate,
                        defaults={'total_votes': 0, 'verified_votes': 0},
                    )
                AuditLog.objects.create(
                    election=self.object,
                    action=AuditLog.Action.UPDATE,
                    performed_by=self.request.user,
                    description=f'Election "{self.object.name}" updated.',
                    ip_address=get_client_ip(self.request),
                )
            messages.success(self.request, 'Election updated.')
            return redirect('voting:election_detail', pk=self.object.pk)
        else:
            return self.render_to_response(self.get_context_data(form=form))


# ===================================================================
# Single ballot entry
# ===================================================================
class BallotCreateView(OperatorRequiredMixin, View):
    template_name = 'voting/ballot_form.html'

    def get_election(self):
        return get_object_or_404(
            Election, pk=self.kwargs['election_pk'], status=Election.Status.OPEN
        )

    def get(self, request, election_pk):
        election = self.get_election()
        form = BallotForm(election=election)
        return render(request, self.template_name, {
            'form': form, 'election': election,
        })


class PublicVoteView(ViewerRequiredMixin, View):
    """Allow any authenticated user to vote in an OPEN election.
    Creates one Ballot per selected candidate and marks them as VERIFIED.
    """
    template_name = 'voting/vote.html'

    def get_election(self):
        return get_object_or_404(Election, pk=self.kwargs['election_pk'], status=Election.Status.OPEN)

    def get(self, request, election_pk):
        election = self.get_election()
        return render(request, self.template_name, {'election': election})

    def post(self, request, election_pk):
        election = self.get_election()
        selected = request.POST.getlist('candidates')
        if not selected:
            messages.error(request, 'Vui lòng chọn ít nhất một ứng viên.')
            return render(request, self.template_name, {'election': election})
        # Validate selection against election rules
        sel_count = len(selected)
        min_c = election.min_choices
        max_c = election.max_choices
        invalid_reason = None
        if min_c and sel_count < min_c:
            invalid_reason = f'Bạn đã chọn {sel_count} ứng viên — tối thiểu là {min_c}.'
        if max_c and sel_count > max_c:
            invalid_reason = f'Bạn đã chọn {sel_count} ứng viên — tối đa là {max_c}.'

        # If invalid and user hasn't confirmed, prompt for confirmation
        if invalid_reason and request.POST.get('confirm') != '1':
            # re-render vote form with confirmation prompt
            return render(request, self.template_name, {
                'election': election,
                'selected': selected,
                'invalid': True,
                'invalid_reason': invalid_reason,
            })

        created = []
        with transaction.atomic():
            # Create a single Ballot record representing this submission

            import uuid
            code = uuid.uuid4().hex[:12].upper()
            # Use first selected candidate as the Ballot.candidate to satisfy existing DB constraint
            first_candidate = get_object_or_404(Candidate, pk=selected[0], election=election)
            ballot = Ballot.objects.create(
                election=election,
                candidate=first_candidate,
                ballot_code=code,
                entered_by=request.user,
                verified_by=(request.user if not invalid_reason else None),
                verification_status=(
                    Ballot.VerificationStatus.VERIFIED if not invalid_reason else Ballot.VerificationStatus.PENDING
                ),
                is_invalid=bool(invalid_reason),
            )

            choices = []
            for cand_id in selected:
                candidate = get_object_or_404(Candidate, pk=cand_id, election=election)
                choices.append(BallotChoice(ballot=ballot, candidate=candidate))

            # Bulk create choices
            BallotChoice.objects.bulk_create(choices)
            # Update summaries only for valid ballots
            if not ballot.is_invalid:
                for choice in choices:
                    VoteSummary.objects.update_or_create(
                        election=election,
                        candidate=choice.candidate,
                        defaults={'total_votes': 0, 'verified_votes': 0},
                    )
                    VoteSummary.objects.filter(election=election, candidate=choice.candidate).update(
                        total_votes=F('total_votes') + 1,
                        verified_votes=F('verified_votes') + 1,
                    )

            # Audit log with candidate list
            AuditLog.objects.create(
                election=election,
                ballot=ballot,
                action=AuditLog.Action.CREATE,
                performed_by=request.user,
                after_data={
                    'ballot_code': ballot.ballot_code,
                    'candidates': [c.candidate.name for c in choices],
                    'is_invalid': ballot.is_invalid,
                },
                description=(
                    f'Public vote by {request.user.username} for {len(choices)} candidate(s).' +
                    (f' Invalid: {invalid_reason}' if invalid_reason else '')
                ),
                ip_address=get_client_ip(request),
            )
            created.append(ballot)

        cache.delete(f'dashboard_{election.pk}')
        if any(b.is_invalid for b in created):
            messages.warning(request, 'Phiếu đã được lưu nhưng được đánh dấu là không hợp lệ.')
        else:
            messages.success(request, f'Cảm ơn — phiếu của bạn cho {len(created)} ứng viên đã được ghi nhận.')
        return redirect('voting:election_detail', pk=election.pk)


# ===================================================================
# Bulk ballot entry
# ===================================================================
class BulkBallotUploadView(OperatorRequiredMixin, View):
    """Handle CSV file upload for bulk ballot entry."""
    template_name = 'voting/bulk_upload.html'

    def get_election(self):
        return get_object_or_404(
            Election, pk=self.kwargs['election_pk'], status=Election.Status.OPEN
        )

    def get(self, request, election_pk):
        election = self.get_election()
        csv_form = BulkBallotUploadForm(election=election)
        text_form = BulkBallotTextForm(election=election)
        return render(request, self.template_name, {
            'csv_form': csv_form, 'text_form': text_form, 'election': election,
        })

    def post(self, request, election_pk):
        election = self.get_election()
        csv_form = BulkBallotUploadForm(election=election)
        text_form = BulkBallotTextForm(election=election)

        action = request.POST.get('action', 'csv')

        if action == 'csv':
            csv_form = BulkBallotUploadForm(
                request.POST, request.FILES, election=election
            )
            if csv_form.is_valid():
                count = self._process_csv(request, election, csv_form.cleaned_rows)
                cache.delete(f'dashboard_{election.pk}')
                messages.success(request, f'{count} ballots imported from CSV.')
                return redirect('voting:election_detail', pk=election.pk)
        elif action == 'text':
            text_form = BulkBallotTextForm(request.POST, election=election)
            if text_form.is_valid():
                count = self._process_text(request, election, text_form.cleaned_rows)
                cache.delete(f'dashboard_{election.pk}')
                messages.success(request, f'{count} ballots imported from pasted data.')
                return redirect('voting:election_detail', pk=election.pk)

        return render(request, self.template_name, {
            'csv_form': csv_form, 'text_form': text_form, 'election': election,
        })

    def _process_csv(self, request, election, rows):
        """Bulk-create ballots from parsed CSV rows."""
        # Accept candidate identifier as either PK or order (both mapped to PK)
        candidate_map = {}
        for c in Candidate.objects.filter(election=election):
            candidate_map[str(c.pk)] = c.pk
            candidate_map[str(c.order)] = c.pk
        chunk_size = getattr(settings, 'BALLOT_BULK_CHUNK_SIZE', 500)
        ballots = []
        for row in rows:
            bc = row['ballot_code'].strip().upper()
            cc = row['candidate_code'].strip()
            cid = candidate_map.get(cc)
            if cid:
                is_invalid = False
                # For single-candidate bulk rows, check election rules
                if election.min_choices and election.min_choices > 1:
                    is_invalid = True
                ballots.append(Ballot(
                    election=election,
                    candidate_id=cid,
                    ballot_code=bc,
                    entered_by=request.user,
                    is_invalid=is_invalid,
                ))

        created = 0
        with transaction.atomic():
            for i in range(0, len(ballots), chunk_size):
                chunk = ballots[i:i + chunk_size]
                Ballot.objects.bulk_create(chunk, ignore_conflicts=False)
                created += len(chunk)
            # Rebuild summaries after bulk insert
            self._rebuild_summaries(election)
            AuditLog.objects.create(
                election=election,
                action=AuditLog.Action.BULK_IMPORT,
                performed_by=request.user,
                after_data={'count': created, 'source': 'csv'},
                description=f'Bulk imported {created} ballots from CSV.',
                ip_address=get_client_ip(request),
            )
        return created

    def _process_text(self, request, election, parsed_rows):
        """Bulk-create ballots from parsed text rows."""
        chunk_size = getattr(settings, 'BALLOT_BULK_CHUNK_SIZE', 500)
        ballots = []
        for row in parsed_rows:
            is_invalid = False
            if election.min_choices and election.min_choices > 1:
                is_invalid = True
            ballots.append(Ballot(
                election=election,
                candidate_id=row['candidate_id'],
                ballot_code=row['ballot_code'],
                entered_by=request.user,
                is_invalid=is_invalid,
            ))

        created = 0
        with transaction.atomic():
            for i in range(0, len(ballots), chunk_size):
                chunk = ballots[i:i + chunk_size]
                Ballot.objects.bulk_create(chunk, ignore_conflicts=False)
                created += len(chunk)
            self._rebuild_summaries(election)
            AuditLog.objects.create(
                election=election,
                action=AuditLog.Action.BULK_IMPORT,
                performed_by=request.user,
                after_data={'count': created, 'source': 'text'},
                description=f'Bulk imported {created} ballots from pasted data.',
                ip_address=get_client_ip(request),
            )
        return created

    @staticmethod
    def _rebuild_summaries(election):
        """Rebuild VoteSummary from actual counts (used after bulk ops)."""
        # Exclude ballots marked as invalid from summaries
        summaries = (
            Ballot.objects.filter(election=election, is_invalid=False)
            .values('candidate')
            .annotate(cnt=Count('id'))
        )
        for row in summaries:
            VoteSummary.objects.update_or_create(
                election=election,
                candidate_id=row['candidate'],
                defaults={
                    'total_votes': row['cnt'],
                    'verified_votes': Ballot.objects.filter(
                        election=election,
                        candidate_id=row['candidate'],
                        verification_status=Ballot.VerificationStatus.VERIFIED,
                    ).count(),
                },
            )


# ===================================================================
# Ballot verification (double-entry workflow)
# ===================================================================
class BallotVerifyListView(OperatorRequiredMixin, ListView):
    """List of ballots pending verification."""
    template_name = 'voting/ballot_verify_list.html'
    context_object_name = 'ballots'
    paginate_by = 50

    def get_queryset(self):
        election = get_object_or_404(Election, pk=self.kwargs['election_pk'])
        return (
            Ballot.objects.filter(
                election=election,
                verification_status=Ballot.VerificationStatus.PENDING,
            )
            .select_related('candidate', 'entered_by')
            .exclude(entered_by=self.request.user)  # Cannot verify own entries
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['election'] = get_object_or_404(Election, pk=self.kwargs['election_pk'])
        return ctx


class BallotVerifyView(OperatorRequiredMixin, View):
    """Verify or reject a single ballot."""
    template_name = 'voting/ballot_verify.html'

    def get(self, request, election_pk, ballot_pk):
        election = get_object_or_404(Election, pk=election_pk)
        ballot = get_object_or_404(
            Ballot, pk=ballot_pk, election=election,
            verification_status=Ballot.VerificationStatus.PENDING,
        )
        form = BallotVerifyForm()
        return render(request, self.template_name, {
            'form': form, 'ballot': ballot, 'election': election,
        })

    def post(self, request, election_pk, ballot_pk):
        election = get_object_or_404(Election, pk=election_pk)
        form = BallotVerifyForm(request.POST)
        if form.is_valid():
            decision = form.cleaned_data['decision']
            comment = form.cleaned_data.get('comment', '')
            with transaction.atomic():
                # Row-level lock (SELECT ... FOR UPDATE)
                ballot = (
                    Ballot.objects
                    .select_for_update()
                    .get(pk=ballot_pk, election=election)
                )
                if ballot.entered_by == request.user:
                    messages.error(request, 'You cannot verify your own entry.')
                    return redirect(
                        'voting:ballot_verify_list', election_pk=election.pk
                    )

                before = {
                    'verification_status': ballot.verification_status,
                    'verified_by': str(ballot.verified_by),
                }
                ballot.verification_status = decision
                ballot.verified_by = request.user
                ballot.version = F('version') + 1
                ballot.save(update_fields=[
                    'verification_status', 'verified_by', 'version', 'updated_at',
                ])

                action = (
                    AuditLog.Action.VERIFY
                    if decision == 'VERIFIED'
                    else AuditLog.Action.REJECT
                )
                AuditLog.objects.create(
                    election=election,
                    ballot=ballot,
                    action=action,
                    performed_by=request.user,
                    before_data=before,
                    after_data={
                        'verification_status': decision,
                        'verified_by': request.user.username,
                        'comment': comment,
                    },
                    description=f'Ballot {ballot.ballot_code} {decision.lower()} by {request.user.username}.',
                    ip_address=get_client_ip(request),
                )

                # Update verified count in summary
                if decision == 'VERIFIED':
                    # Only update summary if ballot is not marked invalid
                    if not ballot.is_invalid:
                        VoteSummary.objects.filter(
                            election=election, candidate=ballot.candidate,
                        ).update(verified_votes=F('verified_votes') + 1)

            cache.delete(f'dashboard_{election.pk}')
            messages.success(request, f'Ballot {ballot.ballot_code} {decision.lower()}.')
            return redirect('voting:ballot_verify_list', election_pk=election.pk)

        ballot = get_object_or_404(Ballot, pk=ballot_pk, election=election)
        return render(request, self.template_name, {
            'form': form, 'ballot': ballot, 'election': election,
        })


# ===================================================================
# Admin dashboard
# ===================================================================
class DashboardView(AdminRequiredMixin, View):
    template_name = 'voting/dashboard.html'

    def get(self, request, election_pk):
        election = get_object_or_404(Election, pk=election_pk)
        data = self._get_dashboard_data(election)
        recent_logs = (
            AuditLog.objects.filter(election=election)
            .select_related('performed_by')[:50]
        )
        return render(request, self.template_name, {
            'election': election,
            'dashboard': data,
            'audit_logs': recent_logs,
        })

    @staticmethod
    def _get_dashboard_data(election):
        cache_key = f'dashboard_{election.pk}'
        data = cache.get(cache_key)
        if data:
            return data
        # VoteSummary stores per-candidate vote counts (one candidate may
        # receive multiple votes per ballot if multi-choice is allowed).
        # Provide both vote-based and ballot-based totals so the UI can show
        # consistent numbers (ballot counts vs vote counts).
        summaries = (
            VoteSummary.objects.filter(election=election)
            .select_related('candidate')
            .order_by('-total_votes')
        )

        # Count actual ballots (exclude invalid ballots)
        total_ballots = Ballot.objects.filter(election=election, is_invalid=False).count()
        verified_ballots = Ballot.objects.filter(
            election=election,
            verification_status=Ballot.VerificationStatus.VERIFIED,
            is_invalid=False,
        ).count()

        candidates = []
        # For each candidate, compute distinct ballots that include them.
        # A ballot may include a candidate via Ballot.candidate (single-choice / bulk)
        # or via BallotChoice for multi-select ballots. Use DISTINCT to avoid double-counting.
        for s in summaries:
            cand = s.candidate
            ballots_qs = Ballot.objects.filter(
                election=election, is_invalid=False
            ).filter(
                Q(candidate=cand) | Q(choices__candidate=cand)
            ).distinct()
            ballot_count = ballots_qs.count()
            verified_count = ballots_qs.filter(
                verification_status=Ballot.VerificationStatus.VERIFIED
            ).count()
            candidates.append({
                'name': cand.name,
                'order': cand.order,
                'total_votes': ballot_count,
                'verified_votes': verified_count,
                # percentage fields filled below after computing denominator
                'percentage': 0,
                'verified_percentage': 0,
            })

        # Normalize percentages so candidate percentages sum to 100%.
        denom = sum(c['total_votes'] for c in candidates)
        for c in candidates:
            if denom:
                c['percentage'] = round((c['total_votes'] / denom) * 100, 2)
                c['verified_percentage'] = round((c['verified_votes'] / denom) * 100, 2)
            else:
                c['percentage'] = 0
                c['verified_percentage'] = 0

        # Keep vote-level total for backward compatibility (sum of VoteSummary)
        total_votes = sum(s.total_votes for s in summaries)

        data = {
            'total_ballots': total_ballots,
            'verified_ballots': verified_ballots,
            'pending_ballots': total_ballots - verified_ballots,
            'total_votes': total_votes,
            'candidates': candidates,
        }
        cache.set(cache_key, data, CACHE_TTL)
        return data


# ===================================================================
# JSON API for AJAX polling
# ===================================================================
@login_required
def api_dashboard_data(request, election_pk):
    """Return dashboard data as JSON for live updates via JS polling."""
    election = get_object_or_404(Election, pk=election_pk)
    data = DashboardView._get_dashboard_data(election)
    return JsonResponse(data)


@login_required
def api_audit_log(request, election_pk):
    """Return recent audit log entries as JSON."""
    election = get_object_or_404(Election, pk=election_pk)
    page = int(request.GET.get('page', 1))
    per_page = 30
    offset = (page - 1) * per_page
    logs = (
        AuditLog.objects.filter(election=election)
        .select_related('performed_by')
        .order_by('-timestamp')[offset:offset + per_page]
    )
    entries = [
        {
            'id': log.pk,
            'action': log.action,
            'description': log.description,
            'user': log.performed_by.username,
            'before': log.before_data,
            'after': log.after_data,
            'timestamp': log.timestamp.isoformat(),
            'ip': log.ip_address,
        }
        for log in logs
    ]
    return JsonResponse({'entries': entries, 'page': page})


# ===================================================================
# Ballot listing (with filters)
# ===================================================================
class BallotListView(ViewerRequiredMixin, ListView):
    template_name = 'voting/ballot_list.html'
    context_object_name = 'ballots'
    paginate_by = 100

    def get_queryset(self):
        election = get_object_or_404(Election, pk=self.kwargs['election_pk'])
        qs = (
            Ballot.objects.filter(election=election)
            .select_related('candidate', 'entered_by', 'verified_by')
        )
        # Filters
        status = self.request.GET.get('status')
        if status in dict(Ballot.VerificationStatus.choices):
            qs = qs.filter(verification_status=status)
        candidate = self.request.GET.get('candidate')
        if candidate:
            qs = qs.filter(candidate__pk=candidate)
        search = self.request.GET.get('q')
        if search:
            qs = qs.filter(ballot_code__icontains=search)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        election = get_object_or_404(Election, pk=self.kwargs['election_pk'])
        ctx['election'] = election
        ctx['candidates'] = election.candidates.all()
        ctx['current_status'] = self.request.GET.get('status', '')
        ctx['current_candidate'] = self.request.GET.get('candidate', '')
        ctx['search_query'] = self.request.GET.get('q', '')
        return ctx


class BallotDetailView(ViewerRequiredMixin, DetailView):
    model = Ballot
    template_name = 'voting/ballot_detail.html'
    context_object_name = 'ballot'

    def get_object(self, queryset=None):
        election = get_object_or_404(Election, pk=self.kwargs['election_pk'])
        return get_object_or_404(Ballot.objects.select_related('candidate', 'entered_by', 'verified_by'), pk=self.kwargs['pk'], election=election)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['election'] = get_object_or_404(Election, pk=self.kwargs['election_pk'])
        return ctx


# ===================================================================
# Audit log view
# ===================================================================
class AuditLogListView(AdminRequiredMixin, ListView):
    template_name = 'voting/audit_log_list.html'
    context_object_name = 'logs'
    paginate_by = 50

    def get_queryset(self):
        election = get_object_or_404(Election, pk=self.kwargs['election_pk'])
        qs = (
            AuditLog.objects.filter(election=election)
            .select_related('performed_by', 'ballot')
        )
        action = self.request.GET.get('action')
        if action in dict(AuditLog.Action.choices):
            qs = qs.filter(action=action)
        user = self.request.GET.get('user')
        if user:
            qs = qs.filter(performed_by__username=user)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['election'] = get_object_or_404(Election, pk=self.kwargs['election_pk'])
        ctx['action_choices'] = AuditLog.Action.choices
        ctx['current_action'] = self.request.GET.get('action', '')
        ctx['current_user'] = self.request.GET.get('user', '')
        return ctx
