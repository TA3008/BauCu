"""
Forms for the voting application.
Includes strict validation, bulk entry, and double-entry verification support.
"""

import csv
import io
import re

from django import forms
from django.core.exceptions import ValidationError
from django.conf import settings

from .models import Election, Candidate, Ballot


# ---------------------------------------------------------------------------
# Election management
# ---------------------------------------------------------------------------
class ElectionForm(forms.ModelForm):
    class Meta:
        model = Election
        fields = ['name', 'description', 'status']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'status': forms.Select(attrs={'class': 'form-select'}),
        }


class CandidateForm(forms.ModelForm):
    class Meta:
        model = Candidate
        fields = ['name', 'code', 'order']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'code': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. C01'}),
            'order': forms.NumberInput(attrs={'class': 'form-control'}),
        }

    def clean_code(self):
        code = self.cleaned_data['code'].strip().upper()
        if not re.match(r'^[A-Z0-9]{1,20}$', code):
            raise ValidationError('Code must be 1-20 alphanumeric characters.')
        return code


CandidateFormSet = forms.inlineformset_factory(
    Election, Candidate,
    form=CandidateForm,
    extra=3,
    can_delete=True,
    min_num=1,
    validate_min=True,
)


# ---------------------------------------------------------------------------
# Single ballot entry
# ---------------------------------------------------------------------------
class BallotForm(forms.ModelForm):
    class Meta:
        model = Ballot
        fields = ['candidate', 'ballot_code']
        widgets = {
            'candidate': forms.Select(attrs={'class': 'form-select'}),
            'ballot_code': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter the ballot code',
            }),
        }

    def __init__(self, *args, election=None, **kwargs):
        super().__init__(*args, **kwargs)
        if election:
            self.fields['candidate'].queryset = Candidate.objects.filter(
                election=election
            )
        self.election = election

    def clean_ballot_code(self):
        code = self.cleaned_data['ballot_code'].strip().upper()
        if not re.match(r'^[A-Z0-9\-]{3,50}$', code):
            raise ValidationError(
                'Ballot code must be 3-50 characters (letters, digits, hyphens).'
            )
        if self.election and Ballot.objects.filter(
            election=self.election, ballot_code=code
        ).exclude(pk=self.instance.pk if self.instance.pk else None).exists():
            raise ValidationError('This ballot code has already been entered for this election.')
        return code


# ---------------------------------------------------------------------------
# Bulk ballot entry (CSV upload)
# ---------------------------------------------------------------------------
class BulkBallotUploadForm(forms.Form):
    """
    Accepts a CSV file with columns: ballot_code, candidate_code
    """
    csv_file = forms.FileField(
        label='CSV File',
        help_text='CSV with columns: ballot_code,candidate_code',
        widget=forms.FileInput(attrs={'class': 'form-control', 'accept': '.csv'}),
    )

    def __init__(self, *args, election=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.election = election

    def clean_csv_file(self):
        f = self.cleaned_data['csv_file']
        if not f.name.endswith('.csv'):
            raise ValidationError('Only CSV files are accepted.')
        if f.size > 5 * 1024 * 1024:  # 5 MB max
            raise ValidationError('File size must be under 5 MB.')

        try:
            content = f.read().decode('utf-8-sig')
        except UnicodeDecodeError:
            raise ValidationError('File must be UTF-8 encoded.')

        reader = csv.DictReader(io.StringIO(content))
        required_cols = {'ballot_code', 'candidate_code'}
        if not required_cols.issubset(set(reader.fieldnames or [])):
            raise ValidationError(
                f'CSV must have columns: {", ".join(required_cols)}. '
                f'Found: {", ".join(reader.fieldnames or [])}'
            )

        rows = list(reader)
        max_rows = getattr(settings, 'MAX_BULK_UPLOAD_SIZE', 10_000)
        if len(rows) > max_rows:
            raise ValidationError(f'Maximum {max_rows} rows allowed per upload.')
        if len(rows) == 0:
            raise ValidationError('CSV file is empty.')

        # Pre-validate rows
        candidate_codes = set(
            Candidate.objects.filter(election=self.election).values_list('code', flat=True)
        )
        existing_ballot_codes = set(
            Ballot.objects.filter(election=self.election).values_list('ballot_code', flat=True)
        )

        errors = []
        seen_codes = set()
        ballot_pattern = re.compile(r'^[A-Z0-9\-]{3,50}$')

        for i, row in enumerate(rows, start=2):  # 2 because row 1 is header
            bc = (row.get('ballot_code') or '').strip().upper()
            cc = (row.get('candidate_code') or '').strip().upper()

            if not bc:
                errors.append(f'Row {i}: ballot_code is empty.')
            elif not ballot_pattern.match(bc):
                errors.append(f'Row {i}: invalid ballot_code "{bc}".')
            elif bc in existing_ballot_codes:
                errors.append(f'Row {i}: ballot_code "{bc}" already exists.')
            elif bc in seen_codes:
                errors.append(f'Row {i}: duplicate ballot_code "{bc}" in file.')
            else:
                seen_codes.add(bc)

            if cc not in candidate_codes:
                errors.append(f'Row {i}: unknown candidate_code "{cc}".')

            if len(errors) > 50:
                errors.append('... too many errors, showing first 50.')
                break

        if errors:
            raise ValidationError(errors)

        self.cleaned_rows = rows
        return f


# ---------------------------------------------------------------------------
# Bulk text-paste entry
# ---------------------------------------------------------------------------
class BulkBallotTextForm(forms.Form):
    """
    Accepts pasted data: one ballot per line, format ballot_code,candidate_code
    """
    data = forms.CharField(
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 12,
            'placeholder': 'ballot_code,candidate_code\nABC-001,C01\nABC-002,C02',
        }),
        label='Ballot Data',
        help_text='One entry per line: ballot_code,candidate_code',
    )

    def __init__(self, *args, election=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.election = election

    def clean_data(self):
        raw = self.cleaned_data['data'].strip()
        if not raw:
            raise ValidationError('No data provided.')

        lines = raw.splitlines()
        max_rows = getattr(settings, 'MAX_BULK_UPLOAD_SIZE', 10_000)
        if len(lines) > max_rows:
            raise ValidationError(f'Maximum {max_rows} entries allowed.')

        candidate_map = dict(
            Candidate.objects.filter(election=self.election).values_list('code', 'pk')
        )
        existing_ballot_codes = set(
            Ballot.objects.filter(election=self.election).values_list('ballot_code', flat=True)
        )

        errors = []
        parsed = []
        seen = set()
        pattern = re.compile(r'^[A-Z0-9\-]{3,50}$')

        for i, line in enumerate(lines, start=1):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = [p.strip().upper() for p in line.split(',')]
            if len(parts) != 2:
                errors.append(f'Line {i}: expected "ballot_code,candidate_code".')
                continue
            bc, cc = parts
            if not pattern.match(bc):
                errors.append(f'Line {i}: invalid ballot_code "{bc}".')
            elif bc in existing_ballot_codes:
                errors.append(f'Line {i}: ballot_code "{bc}" already exists.')
            elif bc in seen:
                errors.append(f'Line {i}: duplicate ballot_code "{bc}".')
            else:
                seen.add(bc)

            if cc not in candidate_map:
                errors.append(f'Line {i}: unknown candidate "{cc}".')
            else:
                parsed.append({'ballot_code': bc, 'candidate_id': candidate_map[cc]})

            if len(errors) > 50:
                errors.append('... too many errors.')
                break

        if errors:
            raise ValidationError(errors)
        if not parsed:
            raise ValidationError('No valid entries found.')

        self.cleaned_rows = parsed
        return raw


# ---------------------------------------------------------------------------
# Verification form
# ---------------------------------------------------------------------------
class BallotVerifyForm(forms.Form):
    """Used by a second operator to verify or reject a ballot."""
    CHOICES = [
        ('VERIFIED', 'Verify – data is correct'),
        ('REJECTED', 'Reject – data has errors'),
    ]
    decision = forms.ChoiceField(
        choices=CHOICES,
        widget=forms.RadioSelect(attrs={'class': 'form-check-input'}),
    )
    comment = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
    )
