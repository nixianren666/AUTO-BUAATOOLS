"""Process-scoped presentation and deployment capabilities; no student data."""
import os
import threading


class StartupPresentation:
    """At most one document gets the splash in each service process lifetime.

    System reboot and service/container restart create a new instance. Merely
    reloading a page, changing accounts, or reconnecting never resets it. This
    is intentionally shared by remote browsers, with no tracking identifier or
    browser storage. A document closed midway is not replayed automatically.
    """
    def __init__(self):
        self._shown = False
        self._lock = threading.Lock()

    def claim(self, prefetch=False):
        if prefetch:
            return False
        with self._lock:
            first = not self._shown
            self._shown = True
            return first


def capabilities():
    mode = os.environ.get('BUAA_RUNTIME_MODE', 'headless')
    desktop = mode == 'desktop'
    return {'mode': 'desktop' if desktop else 'headless',
            'autostart_supported': desktop,
            'exit_behavior': 'application' if desktop else 'management-session'}
