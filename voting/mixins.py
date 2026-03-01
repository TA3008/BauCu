"""
Mixins for role-based access control.
"""
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import PermissionDenied


class AdminRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Only users with ADMIN role may access."""
    def test_func(self):
        return self.request.user.is_admin_role or self.request.user.is_superuser


class OperatorRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """ADMIN and OPERATOR roles may access."""
    def test_func(self):
        u = self.request.user
        return u.is_admin_role or u.is_operator or u.is_superuser


class ViewerRequiredMixin(LoginRequiredMixin):
    """Any logged-in user may access (VIEWER, OPERATOR, ADMIN)."""
    pass


def get_client_ip(request):
    """Extract client IP from request, respecting X-Forwarded-For."""
    xff = request.META.get('HTTP_X_FORWARDED_FOR')
    if xff:
        return xff.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')
