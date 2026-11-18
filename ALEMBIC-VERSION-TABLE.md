# Alembic version-table column width — root cause and fix (2026-11-18)

Branch: `strategy-engine/alembic-version-table`, base 55a3e9a.
Worktree: `~/workspace/mingjian-alembic-vt`. BACKLOG.md untouched.
No merge, no push — main agent verifies and merges.

## 1. The finding (hub Postgres drill, retry-7 report §21.1)

A fresh-database `alembic upgrade 0042` on real Postgres failed at
migration 0007:

```text
sqlalchemy.exc.DataError: value too long for type character varying(32)
[SQL: UPDATE alembic_version SET version_num='0007_backfill_raw_knowledge_status'
      WHERE alembic_version.version_num = '0006_phase6_runtime_hardening']
```

`alembic_version.version_num` was created `VARCHAR(32)` although
`migrations/env.py` configured `version_table_column_type=sa.String(64)`.
Pre-creating the version table as `VARCHAR(128)` made the full
0001→0042 chain pass, so the chain itself is clean — only the
fresh-creation width is wrong.

Revision-id facts, verified independently by scanning
`migrations/versions/*.py`: 44 revisions, 7 longer than 32 characters,
longest 38 (`0037_variable_template_assumption_data`). The first
failure is 0007 (34 chars).

## 2. Root cause: the option does not exist

Read from the installed alembic 1.20.1 source
(`.venv/lib/python3.12/site-packages/alembic/`), not inferred:

1. **`version_table_column_type` occurs zero times in the entire
   alembic package.** It is not a real option in this version.
   `EnvironmentContext.configure()` (`runtime/environment.py:412`)
   ends in `**kw: Any`, so the unknown kwarg in `env.py` was silently
   swallowed into `opts` and never read by anything.
2. **The version table is built by one hardcoded function.**
   `DefaultImpl.version_table_impl()` (`ddl/impl.py:147-178`) builds
   `Column("version_num", String(32), nullable=False)`. It is the
   only definition of `version_table_impl` in the package — no
   dialect overrides it, including `PostgresqlImpl`
   (`ddl/postgresql.py:77-78`), which inherits it.
3. **Only three knobs reach that function.**
   `MigrationContext.__init__` (`runtime/migration.py:198-206`) calls
   `version_table_impl(version_table=..., version_table_schema=...,
   version_table_pk=...)`. There is no width parameter.
4. **The table is created with `checkfirst=True`.**
   `_ensure_version_table()` (`runtime/migration.py:534-539`) calls
   `self._version.create(connection, checkfirst=True)`, and
   `run_migrations()` calls it when no heads exist. A table that
   already exists is left untouched — which is both why the drill's
   pre-created `VARCHAR(128)` table worked and what the fix relies on.

So the `String(64)` in `env.py` never had any effect on any database.
SQLite never showed the bug because SQLite ignores `VARCHAR` widths;
the hub stack DB never showed it because it is built by `create_all`
and has no `alembic_version` table at all. Only a fresh Postgres
upgrade through alembic hits it.

## 3. The fix (minimal, fresh-upgrade only)

`migrations/env.py` (commit 684935a):

- The dead `version_table_column_type=sa.String(64)` argument is
  removed from `context.configure()` — it misled readers into
  thinking the width was configured.
- A `_version_table()` helper builds the version table exactly as
  alembic would (same table name, same `alembic_version_pkc`
  primary-key constraint name) with only the width changed to
  `VERSION_TABLE_COLUMN_WIDTH = 128`. 128 matches the width proven
  by the drill's workaround, with headroom for future revision names.
- `run_migrations_online()` pre-creates that table inside
  `context.begin_transaction()`, before `context.run_migrations()`,
  with `checkfirst=True`. On a fresh database the wide table exists
  before alembic's ensure step runs; on a database that already has
  a version table, nothing happens. Creating it inside the
  transaction preserves the observed all-or-nothing behavior (a
  failed upgrade leaves zero tables on transactional DDL).

No revision was renamed. No migration content changed. The offline
path (`run_migrations_offline`) is untouched: it has no connection
to pre-create against, and offline mode emits alembic's own
`String(32)` CREATE TABLE (`runtime/migration.py`, the `as_sql`
branch of `run_migrations`). No offline usage exists in this repo
(zero `--sql` / offline references in `src`, `tests`, `docs`,
`scripts`), so this residual is documented, not fixed.

Side effect, stated honestly: `env.py` runs for every alembic
invocation, so read-only commands such as `alembic current` on a
fresh database now create an empty `alembic_version` table where
previously none existed. The observable output is unchanged.

## 4. Proof (no live Postgres on this VM)

New tests in `tests/unit/test_migrations.py` (the only test file
that drives alembic; subprocess CLI + real `env.py`, the established
harness):

- `test_fresh_upgrade_creates_wide_version_table` — runs a real
  `alembic upgrade head` against a fresh SQLite database, then reads
  the declared type back with `PRAGMA table_info(alembic_version)`
  (`VARCHAR(128)`), checks the single stored row is a real revision
  id, reflects the table with SQLAlchemy, asserts the reflected type
  length is 128, and renders the reflected `CREATE TABLE` against
  the PostgreSQL dialect, asserting `VARCHAR(128)` in the rendered
  DDL. This is the end-to-end chain: real `env.py` → real created
  table → what Postgres receives.
- `test_all_revision_ids_fit_version_table_width` — parses every
  `migrations/versions/*.py` with `ast`, collects the declared
  revision ids, and asserts the longest fits in 128 and exceeds 32
  (the lower bound pins why the fix exists).

Counts:

- `tests/unit/test_migrations.py`: **5 passed** (3 pre-existing + 2
  new), 17.40s.
- **Red/green proven:** with `migrations/env.py` reverted to base
  (dead option restored), the new end-to-end test FAILED at the
  `VARCHAR(128)` assertion — stock alembic created `VARCHAR(32)`.
  Fix restored, test passes. The test is load-bearing, not
  incidental.
- Ruff on both touched files: exactly the 2 pre-existing I001
  import-order errors, identical to baseline; `ruff format --diff`
  shows only the 2 pre-existing hunks in the test file. No new
  findings.
- Sprint 0 smoke: PASS, evidence reverted.
- No other test file uses alembic; no frontend changes.

## 5. What remains unverified

- **Live Postgres fresh-upgrade proof** — the strongest remaining
  check, to ride on the next hub drill: fresh scratch database, NO
  pre-created version table, `alembic upgrade head` must exit 0,
  `information_schema.columns` must show `character_maximum_length =
  128` for `alembic_version.version_num`, and the stored version
  must be the head revision.
- Offline (`--sql`) output still emits alembic's `String(32)` CREATE
  TABLE (see §3). Nobody uses offline mode in this repo.
- Databases that already have a `String(32)` version table are
  untouched by design (`checkfirst`). No such database is known:
  the stack DB has no version table, SQLite ignores widths.
- The fix is version-pinned by behavior, not by declaration:
  `pyproject.toml` allows `alembic>=1.16,<2.0`. If a future alembic
  honors a width option or changes the hardcoded default, the
  pre-create still wins via `checkfirst`, and the end-to-end test
  still asserts the created width.

## 6. Second task (same branch, separate commit)

Commit 45144f7 adds a doc-only bullet to `FIX-BATCH-3.md` §6
stating the 0043-downgrade limitation found by the same drill
(retry-7 report §21.5): on Postgres, downgrading bigint → integer
fails with `integer out of range` while 63-bit seed rows exist
(narrowing-cast semantics, not a migration defect); the
single-transaction downgrade rolls back cleanly (version stays
0043, rows intact); removing the rows lets the downgrade succeed.
Stated as a known limitation, not a defect.

## 7. Commits on this branch

- 684935a — Pre-create the alembic version table with a wide
  `version_num` column (`migrations/env.py` + 2 tests).
- 45144f7 — Note the 0043-downgrade limitation (doc-only,
  `FIX-BATCH-3.md`).
- (this commit) — This report.
