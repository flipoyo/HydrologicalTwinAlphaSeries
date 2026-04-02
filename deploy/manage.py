#!/usr/bin/env python
"""Django management script for HydrologicalTwin quick deployment."""
import os
import sys


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "hydrotwin_web.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Install the deploy extras:\n"
            "  pip install hydrological-twin-alpha-series[deploy]"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
