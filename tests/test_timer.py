import pytest

from ha_test.helpers import (
    TIMER_ENTITY_IDS,
    assert_timer_active,
    cancel_all_timers,
    classify_outcome,
    snapshot_tracked_states,
    wait_for_active_timer_count,
)
from ha_test.read_timeout import is_test_timeout
from tests.conversation_test import (
    format_failure_message,
    format_state_summary,
    record_failure,
    record_skip,
    run_entity_test,
    usage_from_result,
)
from ha_test.reporting import record_test_result


def setup_all_timers_idle(client):
    cancel_all_timers(client)


def is_timer_active(state):
    assert_timer_active(state)
    return True


def verify_laundry_timer_active(client):
    assert_timer_active(client.get_state("timer.laundry"))


def run_timer_pool_test(
    *,
    request,
    model,
    command,
    ha_client,
    conversation,
    entity_snapshot,
    exact: int | None = None,
    minimum: int | None = None,
):
    setup_all_timers_idle(ha_client)
    result = conversation(command)
    try:
        active = wait_for_active_timer_count(
            ha_client,
            exact=exact,
            minimum=minimum,
        )
        entity_id = active[0]
        state = ha_client.get_state(entity_id)
        after = snapshot_tracked_states(ha_client.get_all_states())
        flags = classify_outcome(
            result,
            entity_snapshot,
            after,
            expected_entity_ids=set(TIMER_ENTITY_IDS),
        )
        record_test_result(
            nodeid=request.node.nodeid,
            model=model,
            outcome="passed",
            latency_ms=result.latency_ms,
            command=command,
            entity_id=entity_id,
            response_speech=result.speech,
            response_type=result.response_type,
            actual_state=format_state_summary(state),
            **flags,
            **usage_from_result(result),
        )
    except Exception as exc:
        after = snapshot_tracked_states(ha_client.get_all_states())
        flags = classify_outcome(
            result,
            entity_snapshot,
            after,
            expected_entity_ids=set(TIMER_ENTITY_IDS),
        )
        if is_test_timeout(exc):
            record_skip(
                nodeid=request.node.nodeid,
                model=model,
                command=command,
                reason=str(exc),
                latency_ms=result.latency_ms,
                result=result,
                **flags,
            )
            pytest.skip(str(exc))
        record_failure(
            nodeid=request.node.nodeid,
            model=model,
            command=command,
            reason=str(exc),
            latency_ms=result.latency_ms,
            result=result,
            **flags,
        )
        raise AssertionError(
            format_failure_message(
                command=command,
                reason=str(exc),
                result=result,
            )
        ) from exc


def test_single_timer(request, ha_client, model, conversation, entity_snapshot):
    run_timer_pool_test(
        request=request,
        model=model,
        command="start the kitchen timer for 5 minutes",
        ha_client=ha_client,
        conversation=conversation,
        entity_snapshot=entity_snapshot,
        exact=1,
    )


def test_multiple_timers(request, ha_client, model, conversation, entity_snapshot):
    run_timer_pool_test(
        request=request,
        model=model,
        command=(
            "start the kitchen timer for 5 minutes and the upstairs timer for 10 minutes"
        ),
        ha_client=ha_client,
        conversation=conversation,
        entity_snapshot=entity_snapshot,
        minimum=2,
    )


@pytest.mark.parametrize(
    ("command", "entity_id", "extra_verify", "expected_entity_ids"),
    [
        (
            "start the pizza timer for 5 minutes",
            "timer.pizza",
            None,
            {"timer.pizza"},
        ),
        (
            "start the pizza timer for 5 minutes and the laundry timer for 10 minutes",
            "timer.pizza",
            verify_laundry_timer_active,
            {"timer.pizza", "timer.laundry"},
        ),
    ],
    ids=["named_timer", "multiple_named_timers"],
)
def test_named_timer(
    request,
    ha_client,
    model,
    conversation,
    entity_snapshot,
    command,
    entity_id,
    extra_verify,
    expected_entity_ids,
):
    run_entity_test(
        nodeid=request.node.nodeid,
        model=model,
        command=command,
        ha_client=ha_client,
        conversation=conversation,
        entity_snapshot=entity_snapshot,
        entity_id=entity_id,
        predicate=is_timer_active,
        setup=setup_all_timers_idle,
        extra_verify=extra_verify,
        expected_entity_ids=expected_entity_ids,
    )
