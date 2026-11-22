"""Isolate the Workhub tests that can run without the internship services."""

import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


def pytest_configure(config):
    temp = TemporaryDirectory()
    config.add_cleanup(temp.cleanup)
    environment = patch.dict(
        os.environ,
        {
            "AGENT_TOKEN": "test-token",
            "DOCUMENT_AGENT_URL": "http://document-agent.invalid",
            "OIDC_CLIENT_ID": "workhub-test",
            "OIDC_CLIENT_SECRET": "test-secret",
            "OIDC_ISSUER": "http://identity.invalid",
            "OUTLINE_API_KEY": "test-token",
            "OUTLINE_PUBLIC_URL": "http://outline.invalid",
            "OUTLINE_URL": "http://outline.invalid",
            "PUBLIC_URL": "http://workhub.invalid",
            "WORKHUB_DB": str(Path(temp.name) / "review.sqlite3"),
        },
    )
    environment.start()
    config.add_cleanup(environment.stop)
