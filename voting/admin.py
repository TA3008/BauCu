from django.contrib import admin
from import_export import resources
from import_export.admin import ImportExportModelAdmin

from .models import Election, Candidate, Ballot, AuditLog, VoteSummary


# ---------------------------------------------------------------------------
# Inline admin classes
# ---------------------------------------------------------------------------
class CandidateInline(admin.TabularInline):
    model = Candidate
    extra = 2


class VoteSummaryInline(admin.TabularInline):
    model = VoteSummary
    readonly_fields = ('candidate', 'total_votes', 'verified_votes', 'last_updated')
    extra = 0
    can_delete = False


# ---------------------------------------------------------------------------
# Resources for import/export
# ---------------------------------------------------------------------------
class BallotResource(resources.ModelResource):
    class Meta:
        model = Ballot
        fields = ('id', 'ref', 'election__name', 'candidate__code', 'ballot_code',
                  'entered_by__username', 'verified_by__username',
                  'verification_status', 'created_at')
        export_order = fields


# ---------------------------------------------------------------------------
# Model admins
# ---------------------------------------------------------------------------
@admin.register(Election)
class ElectionAdmin(admin.ModelAdmin):
    list_display = ('name', 'status', 'created_by', 'created_at')
    list_filter = ('status',)
    search_fields = ('name',)
    inlines = [CandidateInline, VoteSummaryInline]


@admin.register(Candidate)
class CandidateAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'election', 'order')
    list_filter = ('election',)
    search_fields = ('code', 'name')


@admin.register(Ballot)
class BallotAdmin(ImportExportModelAdmin):
    resource_class = BallotResource
    list_display = ('ballot_code', 'election', 'candidate', 'verification_status',
                    'entered_by', 'verified_by', 'created_at')
    list_filter = ('election', 'verification_status', 'candidate')
    search_fields = ('ballot_code', 'ref')
    readonly_fields = ('ref', 'version')
    raw_id_fields = ('entered_by', 'verified_by')


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'election', 'action', 'performed_by', 'description_short')
    list_filter = ('election', 'action')
    search_fields = ('description',)
    readonly_fields = (
        'election', 'ballot', 'action', 'performed_by',
        'before_data', 'after_data', 'description', 'ip_address', 'timestamp',
    )

    def description_short(self, obj):
        return obj.description[:100]
    description_short.short_description = 'Description'

    def has_add_permission(self, request):
        return False  # Audit logs are system-generated only

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(VoteSummary)
class VoteSummaryAdmin(admin.ModelAdmin):
    list_display = ('election', 'candidate', 'total_votes', 'verified_votes', 'last_updated')
    list_filter = ('election',)
    readonly_fields = ('election', 'candidate', 'total_votes', 'verified_votes', 'last_updated')
