"""Explicit authorized-actor fixture for non-ACL unit tests.

Real permission policy is tested independently in test_permissions and the live
three-account test. These tests isolate formatting, confirmation and hierarchy.
"""
from unittest.mock import patch
from . import outline,permissions

def allow_fixture(case):
    replacements=[patch.object(permissions,'document',side_effect=lambda user,doc:doc),
        patch.object(permissions,'project',side_effect=lambda user,code='':outline.project(code)),
        patch.object(permissions,'projects',side_effect=lambda user:outline.projects()),
        patch.object(permissions,'validate_owners'),patch.object(outline,'require_task_access')]
    for p in replacements:p.start();case.addCleanup(p.stop)
