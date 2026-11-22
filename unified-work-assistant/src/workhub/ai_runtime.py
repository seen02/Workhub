"""Cancellable Workhub inference without changing the legacy provider contract."""
import os
from legacy_app.rocketchat.draft import DraftProvider as BaseProvider
from . import job_control


class DraftProvider(BaseProvider):
    async def _post(self, path, body):
        # Report requests previously inherited the server's 60-second idle expiry.
        # Keep only the selected model warm between reports; explicit callers win.
        body={**body,'keep_alive':body.get('keep_alive',os.getenv('WORKHUB_REPORT_KEEP_ALIVE','30m'))}
        return await job_control.wait(super()._post(path, body))
