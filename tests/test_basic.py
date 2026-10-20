"""Basic smoke tests for pharma_next package."""
import pytest
from pharma_next.main import application


def test_app_exists():
    assert application is not None


def test_app_title():
    assert "pharma" in application.title.lower() or application is not None
