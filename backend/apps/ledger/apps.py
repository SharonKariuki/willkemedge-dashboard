from django.apps import AppConfig


class LedgerConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.ledger"
    verbose_name = "General Ledger"

    def ready(self):
        import apps.ledger.signals  # noqa: F401
