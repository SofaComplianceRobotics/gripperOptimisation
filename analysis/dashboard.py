"""
dashboard.py — Thin wrapper redirecting to analysis.app

For backwards compatibility: imports and re-exports the main app functions.
See analysis/app.py for the actual implementation.
"""

from .app import create_app, launch_dashboard

__all__ = ["create_app", "launch_dashboard"]


if __name__ == "__main__":
    launch_dashboard()
