"""URL configuration for the voting app."""
from django.urls import path
from . import views

app_name = 'voting'

urlpatterns = [
    # Elections
    path('', views.ElectionListView.as_view(), name='election_list'),
    path('create/', views.ElectionCreateView.as_view(), name='election_create'),
    path('<int:pk>/', views.ElectionDetailView.as_view(), name='election_detail'),
    path('<int:pk>/edit/', views.ElectionUpdateView.as_view(), name='election_update'),

    # Ballots
    path('<int:election_pk>/ballot/add/', views.BallotCreateView.as_view(), name='ballot_create'),
    path('<int:election_pk>/ballot/bulk/', views.BulkBallotUploadView.as_view(), name='bulk_upload'),
    path('<int:election_pk>/ballots/', views.BallotListView.as_view(), name='ballot_list'),

    # Verification
    path('<int:election_pk>/verify/', views.BallotVerifyListView.as_view(), name='ballot_verify_list'),
    path('<int:election_pk>/verify/<int:ballot_pk>/', views.BallotVerifyView.as_view(), name='ballot_verify'),

    # Dashboard
    path('<int:election_pk>/dashboard/', views.DashboardView.as_view(), name='dashboard'),

    # Audit log
    path('<int:election_pk>/audit/', views.AuditLogListView.as_view(), name='audit_log'),

    # JSON API
    path('api/<int:election_pk>/dashboard/', views.api_dashboard_data, name='api_dashboard'),
    path('api/<int:election_pk>/audit/', views.api_audit_log, name='api_audit_log'),
]
