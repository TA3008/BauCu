"""baucu URL Configuration"""
from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('accounts.urls')),
    path('voting/', include('voting.urls')),
    path('', RedirectView.as_view(url='/voting/', permanent=False)),
]
