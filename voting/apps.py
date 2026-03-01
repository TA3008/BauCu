from django.apps import AppConfig


class VotingConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'voting'
    verbose_name = 'Voting System'

    def ready(self):
        import voting.signals  # noqa: F401
