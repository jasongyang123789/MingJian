"""Storage helpers for variable templates (Sprint 2).

Built-in presets are synthesized from pack code (see ``presets``) and never
touch the database; stored templates live in the ``variable_templates``
table. Every write path validates the full template with the pure validator
before persisting, so an invalid template can never be stored.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from planagent.domain.models import VariableTemplateRecord

from .models import (
    VariableTemplate,
    VariableTemplateCreate,
    VariableTemplateRead,
    VariableTemplateUpdate,
)
from .presets import builtin_template, is_builtin_template_id, known_domain_ids
from .validator import VariableValidationError, validate_template


def record_to_template(record: VariableTemplateRecord) -> VariableTemplate:
    return VariableTemplate(
        id=record.id,
        name=record.name,
        domain_id=record.domain_id,
        description=record.description,
        state_fields=record.state_fields,
        policies=record.policies,
        variables=record.variables,
        formulas=record.formulas or [],
        internal=record.internal,
        assumption_data=record.assumption_data or {},
        is_builtin=False,
    )


def record_to_read(record: VariableTemplateRecord) -> VariableTemplateRead:
    return VariableTemplateRead(
        **record_to_template(record).model_dump(),
        created_at=record.created_at.isoformat(),
        updated_at=record.updated_at.isoformat(),
    )


def builtin_to_read(template: VariableTemplate) -> VariableTemplateRead:
    return VariableTemplateRead(
        **template.model_dump(),
        created_at=None,
        updated_at=None,
    )


async def get_variable_template(session: AsyncSession, template_id: str) -> VariableTemplate | None:
    """Resolve a template id: built-in presets synthesize, stored ids load."""

    if is_builtin_template_id(template_id):
        domain_id = template_id[len("builtin:") :]
        try:
            return builtin_template(domain_id)
        except ValueError:
            return None
    record = await session.get(VariableTemplateRecord, template_id)
    if record is None:
        return None
    return record_to_template(record)


async def _stored_template_records(
    session: AsyncSession, domain_id: str | None = None
) -> list[VariableTemplateRecord]:
    statement = select(VariableTemplateRecord).order_by(VariableTemplateRecord.created_at.asc())
    if domain_id is not None:
        statement = statement.where(VariableTemplateRecord.domain_id == domain_id)
    return list((await session.scalars(statement)).all())


async def list_variable_templates(
    session: AsyncSession, domain_id: str | None = None
) -> list[VariableTemplate]:
    """Built-in presets first (registry order), then stored templates."""

    templates = [
        builtin_template(domain)
        for domain in known_domain_ids()
        if domain_id is None or domain == domain_id
    ]
    records = await _stored_template_records(session, domain_id)
    templates.extend(record_to_template(record) for record in records)
    return templates


async def get_variable_template_read(
    session: AsyncSession, template_id: str
) -> VariableTemplateRead | None:
    """Resolve a template id to its API read shape (with timestamps)."""

    if is_builtin_template_id(template_id):
        domain_id = template_id[len("builtin:") :]
        try:
            return builtin_to_read(builtin_template(domain_id))
        except ValueError:
            return None
    record = await session.get(VariableTemplateRecord, template_id)
    if record is None:
        return None
    return record_to_read(record)


async def list_variable_template_reads(
    session: AsyncSession, domain_id: str | None = None
) -> list[VariableTemplateRead]:
    """Built-in presets first (registry order), then stored templates."""

    reads = [
        builtin_to_read(builtin_template(domain))
        for domain in known_domain_ids()
        if domain_id is None or domain == domain_id
    ]
    records = await _stored_template_records(session, domain_id)
    reads.extend(record_to_read(record) for record in records)
    return reads


def _check_domain(domain_id: str) -> None:
    if domain_id not in known_domain_ids():
        raise ValueError(f"Unknown domain_id: {domain_id}")


async def create_variable_template(
    session: AsyncSession,
    data: VariableTemplateCreate,
    tenant_id: str | None = None,
    preset_id: str | None = None,
) -> VariableTemplateRecord:
    _check_domain(data.domain_id)
    template = VariableTemplate(
        id="pending",
        name=data.name,
        domain_id=data.domain_id,
        description=data.description,
        state_fields=data.state_fields,
        policies=data.policies,
        variables=data.variables,
        formulas=data.formulas,
        internal=data.internal,
        assumption_data=data.assumption_data,
    )
    result = validate_template(template)
    if not result.is_valid:
        raise VariableValidationError(result)
    record = VariableTemplateRecord(
        name=data.name,
        domain_id=data.domain_id,
        description=data.description,
        state_fields=[field.model_dump(mode="json") for field in data.state_fields],
        policies={metric: spec.model_dump(mode="json") for metric, spec in data.policies.items()},
        variables=[variable.model_dump(mode="json") for variable in data.variables],
        formulas=[formula.model_dump(mode="json") for formula in data.formulas],
        internal=dict(data.internal),
        assumption_data=dict(data.assumption_data),
        tenant_id=tenant_id,
        preset_id=preset_id,
    )
    session.add(record)
    await session.flush()
    return record


async def update_variable_template(
    session: AsyncSession,
    record: VariableTemplateRecord,
    data: VariableTemplateUpdate,
) -> VariableTemplateRecord:
    current = record_to_template(record)
    merged = VariableTemplate(
        id=current.id,
        name=data.name if data.name is not None else current.name,
        domain_id=current.domain_id,
        description=data.description if data.description is not None else current.description,
        state_fields=data.state_fields if data.state_fields is not None else current.state_fields,
        policies=data.policies if data.policies is not None else current.policies,
        variables=data.variables if data.variables is not None else current.variables,
        formulas=data.formulas if data.formulas is not None else current.formulas,
        internal=data.internal if data.internal is not None else current.internal,
        assumption_data=(
            data.assumption_data if data.assumption_data is not None else current.assumption_data
        ),
    )
    result = validate_template(merged)
    if not result.is_valid:
        raise VariableValidationError(result)
    record.name = merged.name
    record.description = merged.description
    record.state_fields = [field.model_dump(mode="json") for field in merged.state_fields]
    record.policies = {
        metric: spec.model_dump(mode="json") for metric, spec in merged.policies.items()
    }
    record.variables = [variable.model_dump(mode="json") for variable in merged.variables]
    record.formulas = [formula.model_dump(mode="json") for formula in merged.formulas]
    record.internal = dict(merged.internal)
    record.assumption_data = dict(merged.assumption_data)
    await session.flush()
    return record


async def delete_variable_template(session: AsyncSession, record: VariableTemplateRecord) -> None:
    await session.delete(record)
    await session.flush()
