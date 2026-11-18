from __future__ import annotations

import os
import shutil

import pytest

from planagent.config import reset_settings_cache
from planagent.db import reset_database_cache


@pytest.fixture(autouse=True)
def remove_test_tmp_dir(tmp_path):
    """Delete the test's own tmp_path tree when the test finishes.

    Why: pytest never removes tmp_path dirs mid-session, and every
    scratch SQLite DB costs ~1.6MB (75-table schema, measured
    2026-11-18). A full run leaves ~500 of them behind — ~800MB —
    which overflowed the 794M /dev/shm TMPDIR at 2004 tests
    (939d7eb: 27 tests killed with "database or disk is full").
    Removing each test's own dir at teardown keeps peak usage at
    one live DB (~2MB) instead.

    Why this cannot change test semantics: tmp_path is
    function-scoped and unique per test, so no other test can
    legally observe this directory — the suite has no
    tmp_path_factory use and no basetemp reads (verified
    2026-11-18), and every fixture taking tmp_path is
    function-scoped. Deletion is best-effort (ignore_errors):
    a failed removal only leaks the dir, exactly as before, and
    can never fail the test.

    Ordering: this fixture is defined FIRST so it is set up
    first and torn down last — after every test fixture and
    after the database-cache reset below — so no teardown code
    can observe the removed directory.

    Debugging: set PLANAGENT_KEEP_TEST_TMP=1 to keep the dirs.
    """
    yield
    if os.environ.get("PLANAGENT_KEEP_TEST_TMP") == "1":
        return
    shutil.rmtree(tmp_path, ignore_errors=True)


@pytest.fixture(autouse=True)
def release_cached_database_and_settings_between_tests():
    """Prevent one test's cached database engine and settings from leaking into another test.

    get_settings() is lru_cached: without the settings reset, a test
    that sets PLANAGENT_DATABASE_URL keeps its URL cached for every
    later test that does not set its own — a latent order-dependence.
    (Exposed 2026-11-18 by the tmp-path cleanup above: the stale URL
    pointed into a deleted tmp dir. See TMPFS-DIET.md section 6.)
    """
    yield
    reset_database_cache()
    reset_settings_cache()
