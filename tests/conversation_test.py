"""Helpers for running conversational tests with rich failure reporting."""

from __future__ import annotations

import json
from typing import Any, Callable

from ha_test.helpers import (
    classify_outcome,
    get_changed_entities,
    is_clarification,
    snapshot_tracked_states,
    wait_and_assert,
)
from ha_test.reporting import record_test_result


def format_state_summary(state: dict[str, Any] | None) -> str | None:
    if state is None:
        return None
    summary = {"entity_id": state.get("entity_id"), "state": state.get("state")}
    attributes = state.get("attributes") or {}
    for key in ("temperature", "brightness", "hvac_mode", "friendly_name"):
        if key in attributes:
            summary[key] = attributes[key]
    return json.dumps(summary, sort_keys=True)


def format_failure_message(
    *,
    command: str,
    reason: str,
    entity_id: str | None = None,
    result: Any | None = None,
    actual_state: dict[str, Any] | None = None,
    changed_entities: list[str] | None = None,
) -> str:
    lines = [
        f"Command: {command!r}",
        f"Reason: {reason}",
    ]
    if entity_id:
        lines.append(f"Entity: {entity_id}")
    if result is not None:
        lines.append(f"Response type: {getattr(result, 'response_type', None)}")
        speech = getattr(result, "speech", None)
        if speech:
            lines.append(f"Assistant said: {speech}")
    if actual_state is not None:
        lines.append(f"Actual state: {format_state_summary(actual_state)}")
    if changed_entities:
        lines.append(f"Changed entities: {', '.join(changed_entities)}")
    return "\n".join(lines)


def record_failure(
    *,
    nodeid: str,
    model: str,
    command: str,
    reason: str,
    latency_ms: float = 0.0,
    entity_id: str | None = None,
    result: Any | None = None,
    actual_state: dict[str, Any] | None = None,
    changed_entities: list[str] | None = None,
    clarification: bool = False,
    hallucination: bool = False,
    incorrect_entity_targeting: bool = False,
) -> None:
    record_test_result(
        nodeid=nodeid,
        model=model,
        outcome="failed",
        latency_ms=latency_ms,
        command=command,
        entity_id=entity_id,
        failure_reason=reason,
        response_speech=getattr(result, "speech", None) if result else None,
        response_type=getattr(result, "response_type", None) if result else None,
        actual_state=format_state_summary(actual_state),
        changed_entities=changed_entities,
        clarification=clarification,
        hallucination=hallucination,
        incorrect_entity_targeting=incorrect_entity_targeting,
    )


def run_entity_test(
    *,
    nodeid: str,
    model: str,
    command: str,
    ha_client,
    conversation,
    entity_snapshot: dict[str, dict[str, Any]],
    entity_id: str,
    predicate: Callable[[dict[str, Any]], bool],
    setup: Callable | None = None,
    verify: Callable[[dict[str, Any]], None] | None = None,
    timeout: float = 25.0,
) -> None:
    if setup:
        setup(ha_client)

    result = conversation(command)
    try:
        state = wait_and_assert(ha_client, entity_id, predicate, timeout=timeout)
        if verify:
            verify(state)
        after = snapshot_tracked_states(ha_client.get_all_states())
        flags = classify_outcome(result, entity_snapshot, after)
        record_test_result(
            nodeid=nodeid,
            model=model,
            outcome="passed",
            latency_ms=result.latency_ms,
            command=command,
            entity_id=entity_id,
            response_speech=result.speech,
            response_type=result.response_type,
            actual_state=format_state_summary(state),
            **flags,
        )
    except Exception as exc:
        actual_state = ha_client.get_state(entity_id)
        after = snapshot_tracked_states(ha_client.get_all_states())
        flags = classify_outcome(result, entity_snapshot, after)
        record_failure(
            nodeid=nodeid,
            model=model,
            command=command,
            reason=str(exc),
            latency_ms=result.latency_ms,
            entity_id=entity_id,
            result=result,
            actual_state=actual_state,
            **flags,
        )
        raise AssertionError(
            format_failure_message(
                command=command,
                entity_id=entity_id,
                reason=str(exc),
                result=result,
                actual_state=actual_state,
            )
        ) from exc


def run_negative_test(
    *,
    nodeid: str,
    model: str,
    command: str,
    ha_client,
    conversation,
    entity_snapshot: dict[str, dict[str, Any]],
) -> None:
    before = snapshot_tracked_states(ha_client.get_all_states())
    result = conversation(command)
    after = snapshot_tracked_states(ha_client.get_all_states())
    flags = classify_outcome(result, before, after)
    changed = get_changed_entities(before, after)
    try:
        if changed:
            details = []
            for entity_id in changed:
                old = before[entity_id].get("state")
                new = after[entity_id].get("state")
                details.append(f"{entity_id}: {old!r} -> {new!r}")
            raise AssertionError(f"Unexpected state changes: {'; '.join(details)}")
        record_test_result(
            nodeid=nodeid,
            model=model,
            outcome="passed",
            latency_ms=result.latency_ms,
            command=command,
            response_speech=result.speech,
            response_type=result.response_type,
            **flags,
        )
    except AssertionError as exc:
        record_failure(
            nodeid=nodeid,
            model=model,
            command=command,
            reason=str(exc),
            latency_ms=result.latency_ms,
            result=result,
            changed_entities=changed,
            hallucination=True,
            **{key: value for key, value in flags.items() if key != "hallucination"},
        )
        raise AssertionError(
            format_failure_message(
                command=command,
                reason=str(exc),
                result=result,
                changed_entities=changed,
            )
        ) from exc


def run_implicit_choice_test(
    *,
    nodeid: str,
    model: str,
    command: str,
    ha_client,
    conversation,
    entity_snapshot: dict[str, dict[str, Any]],
    choices: list[tuple[str, Callable[[dict[str, Any]], bool]]],
    setup: Callable | None = None,
    accept_clarification: bool = True,
    timeout: float = 25.0,
) -> None:
    if setup:
        setup(ha_client)

    result = conversation(command)
    after = snapshot_tracked_states(ha_client.get_all_states())
    flags = classify_outcome(result, entity_snapshot, after)
    clarified = accept_clarification and is_clarification(result)

    matched_entity_id: str | None = None
    matched_state: dict[str, Any] | None = None
    errors: list[str] = []

    if not clarified:
        for entity_id, predicate in choices:
            try:
                matched_state = wait_and_assert(ha_client, entity_id, predicate, timeout=timeout)
                matched_entity_id = entity_id
                break
            except Exception as exc:
                errors.append(f"{entity_id}: {exc}")

    if clarified or matched_entity_id is not None:
        record_test_result(
            nodeid=nodeid,
            model=model,
            outcome="passed",
            latency_ms=result.latency_ms,
            command=command,
            entity_id=matched_entity_id,
            response_speech=result.speech,
            response_type=result.response_type,
            actual_state=format_state_summary(matched_state),
            clarification=clarified,
            **{key: value for key, value in flags.items() if key != "clarification"},
        )
        return

    reason = (
        "Command did not clarify and did not match any acceptable entity: "
        + "; ".join(errors)
    )
    record_failure(
        nodeid=nodeid,
        model=model,
        command=command,
        reason=reason,
        latency_ms=result.latency_ms,
        result=result,
        **flags,
    )
    raise AssertionError(
        format_failure_message(
            command=command,
            reason=reason,
            result=result,
        )
    )

