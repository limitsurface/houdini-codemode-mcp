from __future__ import annotations

import math

import pytest

from houdini_codemode.protocol import (
    HARD_MAX_CONTAINER_ITEMS,
    ExecutionRequest,
    RequestValidationError,
    SourceCompileError,
    check_source,
)


def test_request_defaults_and_wire_shape() -> None:
    request = ExecutionRequest.from_inputs(
        "result.emit(args['value'])",
        args={"value": 3},
        run_id="run-1",
    )
    request.compile()

    wire = request.to_wire_dict()

    assert wire["run_id"] == "run-1"
    assert wire["args"] == {"value": 3}
    assert request.instance.host == "localhost"
    assert request.instance.port == 18811
    assert request.policy.undo_group is True


def test_policy_hard_limits_are_clamped() -> None:
    request = ExecutionRequest.from_inputs(
        "pass",
        policy={"max_container_items": HARD_MAX_CONTAINER_ITEMS + 1},
    )

    assert request.policy.max_container_items == HARD_MAX_CONTAINER_ITEMS


@pytest.mark.parametrize(
    "args",
    [
        {"value": math.nan},
        {"value": math.inf},
        {1: "not a string key"},
        {"value": object()},
    ],
)
def test_args_must_be_finite_json(args) -> None:
    with pytest.raises(RequestValidationError, match="finite JSON"):
        ExecutionRequest.from_inputs("pass", args=args)


def test_unknown_policy_fields_are_rejected() -> None:
    with pytest.raises(RequestValidationError, match="Unknown policy fields"):
        ExecutionRequest.from_inputs("pass", policy={"surprise": True})


def test_trusted_local_release_rejects_non_loopback_endpoint() -> None:
    with pytest.raises(RequestValidationError, match="loopback"):
        ExecutionRequest.from_inputs(
            "pass",
            instance={"host": "houdini.example.com", "port": 18811},
        )


def test_invalid_source_has_structured_compile_details() -> None:
    request = ExecutionRequest.from_inputs("if True print('broken')")

    with pytest.raises(SourceCompileError) as caught:
        request.compile()

    assert caught.value.lineno == 1
    assert caught.value.offset is not None


def test_check_source_never_contacts_houdini() -> None:
    success = check_source("result.emit(1)")
    failure = check_source("if True print(1)")

    assert success["ok"] is True
    assert success["meta"]["completion"] == "not_started"
    assert failure["ok"] is False
    assert failure["error"]["category"] == "compile"
    assert failure["error"]["details"]["line"] == 1
