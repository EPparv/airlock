"""Owner-selected Mail and Calendar operations on macOS. Never called by discovery."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from .core import Denied


class NativeApps:
    def call(self, operation, value=None):
        if sys.platform != 'darwin':
            raise Denied('Open the Mac app to use Apple Mail and Calendar.')
        try:
            run = subprocess.run(
                ['/usr/bin/osascript', '-l', 'JavaScript', str(Path(__file__).with_name('device_apps.js')), operation],
                input=json.dumps(value or {}).encode(), capture_output=True, timeout=90, check=True,
            )
            return json.loads(run.stdout)
        except (subprocess.SubprocessError, ValueError, OSError):
            raise Denied('Check Mail or Calendar and allow Airlock in System Settings → Privacy & Security → Automation.') from None

    def sources(self, source):
        if source not in ('mail', 'calendar'):
            raise Denied('Choose Mail or Calendar.')
        return self.call(source)

    def perform(self, kind, payload, attachment):
        if not attachment:
            return self.call(kind, payload)
        with tempfile.TemporaryDirectory(prefix='airlock-attachment-') as folder:
            path = Path(folder) / attachment['name']
            path.write_bytes(attachment['bytes'])
            os.chmod(path, 0o600)
            return self.call(kind, {**payload, 'attachmentPath': str(path)})


class ExampleApps:
    def sources(self, source):
        if source == 'mail':
            return [{'title': 'Notes from our call', 'recipient': 'Mara Ellis <mara@example.com>'}]
        if source == 'calendar':
            return [{'title': 'Cypress investor meeting', 'recipients': ['mara@example.com', 'jon@example.com']}]
        raise Denied('Choose Mail or Calendar.')

    def perform(self, kind, payload, attachment):
        return True
