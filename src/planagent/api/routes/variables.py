"""Variable-table endpoints (Sprint 2, PRD deltas D2/D3).

- ``POST /variables/validate`` validates a submitted variable set without
  creating anything. It always returns 200: the verdict lives in the payload
  (``is_valid``), and validation is a pure function — no database writes,
  no LLM calls.
- ``/variable-templates`` CRUD manages stored templates. Built-in presets
  (``builtin:<domain_id>``) appear in list/get responses and are read-only:
  create a stored template to customize them.
- ``GET /runs/{run_id}/variables`` retrieves the template snapshot +
  bindings + validation result stored with a simulation run at creation
  time (audit trail).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from planagent.db import get_session
from planagent.domain.models import SimulationRun, VariableTemplateRecord
from planagent.services.variables import (
    VariableRunRead,
    VariableSet,
    VariableTemplate,
    VariableTemplateCreate,
    VariableTemplateRead,
    VariableTemplateUpdate,
    VariableValidationError,
    VariableValidationResult,
    validate_variable_set,
)
from planagent.services.variables.store import (
    create_variable_template,
    delete_variable_template,
    get_variable_template,
    get_variable_template_read,
    list_variable_template_reads,
    record_to_read,
    update_variable_template,
)

router = APIRouter()


def _validation_failed_detail(exc: VariableValidationError) -> dict:
    return {
        "code": "variable_validation_failed",
        "message": "Variable validation failed.",
        "validation": exc.result.model_dump(mode="json"),
    }


@router.post("/variables/validate", response_model=VariableValidationResult)
async def validate_variable_table(variable_set: VariableSet) -> VariableValidationResult:
    return validate_variable_set(variable_set)


@router.post("/variable-templates", response_model=VariableTemplateRead, status_code=201)
async def create_template(
    payload: VariableTemplateCreate,
    session: AsyncSession = Depends(get_session),
) -> VariableTemplateRead:
    try:
        record = await create_variable_template(session, payload)
    except VariableValidationError as exc:
        raise HTTPException(status_code=400, detail=_validation_failed_detail(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await session.commit()
    await session.refresh(record)
    return record_to_read(record)


@router.get("/variable-templates", response_model=list[VariableTemplateRead])
async def list_templates(
    domain_id: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> list[VariableTemplateRead]:
    return await list_variable_template_reads(session, domain_id)


@router.get("/variable-templates/{template_id}", response_model=VariableTemplateRead)
async def get_template(
    template_id: str,
    session: AsyncSession = Depends(get_session),
) -> VariableTemplateRead:
    template = await get_variable_template_read(session, template_id)
    if template is None:
        raise HTTPException(
            status_code=404, detail=f"Variable template {template_id} was not found."
        )
    return template


async def _stored_record_or_raise(
    session: AsyncSession, template_id: str
) -> VariableTemplateRecord:
    template = await get_variable_template(session, template_id)
    if template is None:
        raise HTTPException(
            status_code=404, detail=f"Variable template {template_id} was not found."
        )
    if template.is_builtin:
        raise HTTPException(
            status_code=400,
            detail=f"Built-in template {template_id} is read-only; create a stored template instead.",
        )
    record = await session.get(VariableTemplateRecord, template_id)
    if record is None:  # pragma: no cover - get_variable_template found it above
        raise HTTPException(
            status_code=404, detail=f"Variable template {template_id} was not found."
        )
    return record


@router.put("/variable-templates/{template_id}", response_model=VariableTemplateRead)
async def update_template(
    template_id: str,
    payload: VariableTemplateUpdate,
    session: AsyncSession = Depends(get_session),
) -> VariableTemplateRead:
    record = await _stored_record_or_raise(session, template_id)
    try:
        record = await update_variable_template(session, record, payload)
    except VariableValidationError as exc:
        raise HTTPException(status_code=400, detail=_validation_failed_detail(exc)) from exc
    await session.commit()
    await session.refresh(record)
    return record_to_read(record)


@router.delete("/variable-templates/{template_id}", status_code=204)
async def delete_template(
    template_id: str,
    session: AsyncSession = Depends(get_session),
) -> None:
    record = await _stored_record_or_raise(session, template_id)
    await delete_variable_template(session, record)
    await session.commit()


@router.get("/runs/{run_id}/variables", response_model=VariableRunRead)
async def get_run_variables(
    run_id: str,
    session: AsyncSession = Depends(get_session),
) -> VariableRunRead:
    run = await session.get(SimulationRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Simulation run {run_id} was not found.")
    fragment = (run.configuration or {}).get("variables")
    if not isinstance(fragment, dict):
        raise HTTPException(
            status_code=404,
            detail=f"Simulation run {run_id} has no attached variable bindings.",
        )
    template = fragment.get("template")
    bindings = fragment.get("bindings")
    validation = fragment.get("validation")
    return VariableRunRead(
        run_id=run.id,
        template=VariableTemplate.model_validate(template) if template is not None else None,
        bindings=VariableSet.model_validate(bindings) if bindings is not None else None,
        validation=(
            VariableValidationResult.model_validate(validation) if validation is not None else None
        ),
    )
