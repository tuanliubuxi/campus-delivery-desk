"""Keep test-generated media out of the deployable data directory."""

import pytest


@pytest.fixture(autouse=True)
def isolate_test_storage(settings, tmp_path):
    """Every test gets private media and upload scratch space.

    Individual tests may replace these paths with another test-local directory.
    Neither case may fall back to the application's persistent ``data/media``.
    """
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.TMP_ROOT = tmp_path / "tmp"
