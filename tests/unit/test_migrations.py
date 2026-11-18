from __future__ import annotations

import ast
import os
from pathlib import Path
import sqlite3
from contextlib import closing
import subprocess
import sys

from sqlalchemy import MetaData, Table, create_engine
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable


def test_sqlite_upgrade_head_keeps_portable_embedding_column(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    database_path = tmp_path / "community-migrations.db"
    env = os.environ.copy()
    env["PLANAGENT_DATABASE_URL"] = f"sqlite+aiosqlite:///{database_path.resolve().as_posix()}"

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    with closing(sqlite3.connect(database_path)) as connection:
        columns = {
            row[1]: row[2] for row in connection.execute("PRAGMA table_info(knowledge_graph_nodes)")
        }
        indexes = {row[1] for row in connection.execute("PRAGMA index_list(knowledge_graph_nodes)")}
        recommendation_unique_columns = {
            tuple(column[2] for column in connection.execute(f'PRAGMA index_info("{index[1]}")'))
            for index in connection.execute("PRAGMA index_list(recommendation_versions)")
            if index[2]
        }

    assert columns["embedding_vector"] == "TEXT"
    assert "ix_knowledge_graph_nodes_embedding_vector" not in indexes
    assert ("session_id", "version_number") in recommendation_unique_columns


def test_recommendation_integrity_migration_repairs_existing_duplicates(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    database_path = tmp_path / "community-existing-recommendations.db"
    env = os.environ.copy()
    env["PLANAGENT_DATABASE_URL"] = f"sqlite+aiosqlite:///{database_path.resolve().as_posix()}"

    before_constraint = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "0027_auth_token_version"],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert before_constraint.returncode == 0, before_constraint.stdout + before_constraint.stderr

    with closing(sqlite3.connect(database_path)) as connection:
        connection.execute(
            "INSERT INTO strategic_sessions "
            "(id, name, topic, domain_id, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                "session-1",
                "Migration repair",
                "Repair duplicate recommendation versions",
                "corporate",
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
            ),
        )
        connection.executemany(
            "INSERT INTO recommendation_versions "
            "(id, session_id, version_number, trigger_type, recommendation_summary, generated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                (
                    "version-later",
                    "session-1",
                    1,
                    "scheduled_refresh",
                    "later",
                    "2026-01-02T00:00:00+00:00",
                ),
                (
                    "version-earlier",
                    "session-1",
                    1,
                    "initial_result",
                    "earlier",
                    "2026-01-01T00:00:00+00:00",
                ),
            ],
        )
        connection.commit()

    repaired = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert repaired.returncode == 0, repaired.stdout + repaired.stderr

    with closing(sqlite3.connect(database_path)) as connection:
        rows = connection.execute(
            "SELECT id, version_number FROM recommendation_versions "
            "WHERE session_id = ? ORDER BY version_number",
            ("session-1",),
        ).fetchall()

    assert rows == [("version-earlier", 1), ("version-later", 2)]


def _run_alembic(
    repo_root: Path, env: dict[str, str], *args: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_seed_columns_become_bigint_and_keep_rows(tmp_path: Path) -> None:
    """Fix batch 3, migration 0043: seed columns widen Integer -> BigInteger.

    SQLite renders BigInteger as BIGINT, so the type change is directly
    observable here even though SQLite integers were already 64-bit.
    Seeded 63-bit rows must survive upgrade, downgrade, and re-upgrade
    with their values intact.
    """
    repo_root = Path(__file__).resolve().parents[2]
    database_path = tmp_path / "seed-bigint.db"
    env = os.environ.copy()
    env["PLANAGENT_DATABASE_URL"] = f"sqlite+aiosqlite:///{database_path.resolve().as_posix()}"

    before = _run_alembic(repo_root, env, "upgrade", "0042_direction_override_record")
    assert before.returncode == 0, before.stdout + before.stderr

    big_run_seed = 2**62 + 7
    big_fit_seed = 2**62 + 12345
    with closing(sqlite3.connect(database_path)) as connection:
        connection.execute(
            "INSERT INTO simulation_runs "
            "(id, domain_id, actor_template, execution_mode, status, tick_count, "
            "seed, configuration, summary, processing_attempts, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "run-seed",
                "corporate",
                "default",
                "INLINE",
                "COMPLETED",
                2,
                big_run_seed,
                "{}",
                "{}",
                0,
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
            ),
        )
        connection.execute(
            "INSERT INTO calibration_fits "
            "(id, kind, domain_id, ridge_strength, seed, bootstrap_draws, level, "
            "source_run_ids, n_observations, changes, inputs_hash, application, "
            "created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "fit-seed",
                "rule_weights",
                "corporate",
                1.0,
                big_fit_seed,
                10,
                0.95,
                "[]",
                0,
                "{}",
                "sha256:fixbatch3",
                "{}",
                "2026-01-01T00:00:00+00:00",
            ),
        )
        connection.commit()

    def column_types() -> tuple[dict[str, str], dict[str, str]]:
        with closing(sqlite3.connect(database_path)) as connection:
            runs = {
                row[1]: row[2]
                for row in connection.execute("PRAGMA table_info(simulation_runs)")
            }
            fits = {
                row[1]: row[2]
                for row in connection.execute("PRAGMA table_info(calibration_fits)")
            }
        return runs, fits

    def stored_seeds() -> tuple[int, int]:
        with closing(sqlite3.connect(database_path)) as connection:
            run_seed = connection.execute(
                "SELECT seed FROM simulation_runs WHERE id = ?", ("run-seed",)
            ).fetchone()[0]
            fit_seed = connection.execute(
                "SELECT seed FROM calibration_fits WHERE id = ?", ("fit-seed",)
            ).fetchone()[0]
        return run_seed, fit_seed

    runs, fits = column_types()
    assert runs["seed"] == "INTEGER"
    assert fits["seed"] == "INTEGER"

    upgraded = _run_alembic(repo_root, env, "upgrade", "head")
    assert upgraded.returncode == 0, upgraded.stdout + upgraded.stderr
    runs, fits = column_types()
    assert runs["seed"] == "BIGINT"
    assert fits["seed"] == "BIGINT"
    assert stored_seeds() == (big_run_seed, big_fit_seed)

    downgraded = _run_alembic(repo_root, env, "downgrade", "0042_direction_override_record")
    assert downgraded.returncode == 0, downgraded.stdout + downgraded.stderr
    runs, fits = column_types()
    assert runs["seed"] == "INTEGER"
    assert fits["seed"] == "INTEGER"
    assert stored_seeds() == (big_run_seed, big_fit_seed)

    reupgraded = _run_alembic(repo_root, env, "upgrade", "head")
    assert reupgraded.returncode == 0, reupgraded.stdout + reupgraded.stderr
    runs, fits = column_types()
    assert runs["seed"] == "BIGINT"
    assert fits["seed"] == "BIGINT"
    assert stored_seeds() == (big_run_seed, big_fit_seed)


def _revision_ids(repo_root: Path) -> list[str]:
    """All revision ids declared by the migration scripts."""
    versions_dir = repo_root / "migrations" / "versions"
    revision_ids: list[str] = []
    for path in sorted(versions_dir.glob("*.py")):
        tree = ast.parse(path.read_text())
        for node in tree.body:
            if (
                isinstance(node, ast.Assign)
                and any(
                    isinstance(target, ast.Name) and target.id == "revision"
                    for target in node.targets
                )
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            ):
                revision_ids.append(node.value.value)
    return revision_ids


def test_all_revision_ids_fit_version_table_width() -> None:
    """Every revision id must fit the wide version-table column.

    The width (128) is `VERSION_TABLE_COLUMN_WIDTH` in
    `migrations/env.py`. The lower bound pins why the fix exists:
    alembic hardcodes String(32), and revision ids longer than that
    killed a fresh Postgres upgrade at 0007.
    """
    repo_root = Path(__file__).resolve().parents[2]
    revision_ids = _revision_ids(repo_root)
    assert revision_ids, "no revision ids found under migrations/versions"
    longest = max(revision_ids, key=len)
    assert len(longest) <= 128, f"revision id {longest!r} exceeds the 128-char version column"
    assert len(longest) > 32, "expected at least one revision id to exceed alembic's String(32)"


def test_fresh_upgrade_creates_wide_version_table(tmp_path: Path) -> None:
    """A fresh upgrade must create alembic_version with a wide column.

    Proves `migrations/env.py` pre-creates the version table before
    alembic's own ensure step (which hardcodes String(32)): the
    declared type is read back from the real upgraded database, and
    the reflected table's CREATE is rendered against the PostgreSQL
    dialect to show what Postgres receives.
    """
    repo_root = Path(__file__).resolve().parents[2]
    database_path = tmp_path / "version-table-width.db"
    env = os.environ.copy()
    env["PLANAGENT_DATABASE_URL"] = f"sqlite+aiosqlite:///{database_path.resolve().as_posix()}"

    upgraded = _run_alembic(repo_root, env, "upgrade", "head")
    assert upgraded.returncode == 0, upgraded.stdout + upgraded.stderr

    with closing(sqlite3.connect(database_path)) as connection:
        declared = {
            row[1]: row[2] for row in connection.execute("PRAGMA table_info(alembic_version)")
        }
        stored = connection.execute("SELECT version_num FROM alembic_version").fetchall()

    assert declared["version_num"] == "VARCHAR(128)"
    assert len(stored) == 1
    assert stored[0][0] in _revision_ids(repo_root)

    engine = create_engine(f"sqlite:///{database_path.resolve().as_posix()}")
    try:
        reflected = Table("alembic_version", MetaData(), autoload_with=engine)
        assert reflected.c.version_num.type.length == 128
        rendered = str(CreateTable(reflected).compile(dialect=postgresql.dialect()))
        assert "VARCHAR(128)" in rendered
    finally:
        engine.dispose()
