from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """
    Custom user model with role-based access control.
    Roles:
        - ADMIN: full access to dashboard, approval, and management
        - OPERATOR: can enter and verify ballots
        - VIEWER: read-only access to results
    """

    class Role(models.TextChoices):
        ADMIN = 'ADMIN', 'Administrator'
        OPERATOR = 'OPERATOR', 'Data Operator'
        VIEWER = 'VIEWER', 'Viewer'

    role = models.CharField(
        max_length=10,
        choices=Role.choices,
        default=Role.OPERATOR,
        db_index=True,
    )

    class Meta:
        db_table = 'accounts_user'
        ordering = ['username']

    def __str__(self):
        return f'{self.username} ({self.get_role_display()})'

    # Convenience helpers
    @property
    def is_admin_role(self):
        return self.role == self.Role.ADMIN

    @property
    def is_operator(self):
        return self.role == self.Role.OPERATOR

    @property
    def is_viewer(self):
        return self.role == self.Role.VIEWER
