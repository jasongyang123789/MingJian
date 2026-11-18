from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import Column, MetaData, PrimaryKeyConstraint, Table, engine_from_config, pool
import sqlalchemy as sa

from planagent.config import get_settings
from planagent.domain.models import Base


config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def sync_database_url() -> str:
    url = get_settings().database_url
    if "+aiosqlite" in url:
        return url.replace("+aiosqlite", "")
    return url


config.set_main_option("sqlalchemy.url", sync_database_url())
target_metadata = Base.metadata

# Width of the `alembic_version.version_num` column created on fresh
# upgrades. Alembic 1.20.1 has no `version_table_column_type` option:
# `EnvironmentContext.configure()` silently accepts unknown keyword
# arguments, and `DefaultImpl.version_table_impl()` hardcodes
# `String(32)` — no dialect overrides it. Seven revision ids exceed 32
# characters (longest 38), so a fresh Postgres upgrade died at 0007
# with `value too long for type character varying(32)`. The version
# table is therefore pre-created below with a wide column; alembic's
# own ensure step uses `checkfirst=True` and leaves an existing table
# untouched. 128 matches the width proven by the hub Postgres drill's
# workaround, with headroom for future revision names.
VERSION_TABLE_COLUMN_WIDTH = 128


def _version_table() -> Table:
    """Build the alembic version table as alembic would, but wide.

    Mirrors `DefaultImpl.version_table_impl()` (same table name, same
    `alembic_version_pkc` primary-key constraint name) with only the
    `version_num` width changed.
    """
    table = Table(
        "alembic_version",
        MetaData(),
        Column("version_num", sa.String(VERSION_TABLE_COLUMN_WIDTH), nullable=False),
    )
    table.append_constraint(PrimaryKeyConstraint("version_num", name="alembic_version_pkc"))
    return table


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            # Fresh databases only: create the version table with the
            # wide column before the first migration runs, so alembic
            # does not create its hardcoded String(32) column instead.
            # `checkfirst=True` leaves an existing table untouched.
            _version_table().create(connection, checkfirst=True)
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
