#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys


def main():
    """Run administrative tasks."""
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    # Everything a command changes is audited as "Server command: <name>",
    # so a `--apply` run from the Render shell is on the director's log.
    from apps.accounts.audit_context import start_command

    start_command(sys.argv)
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
