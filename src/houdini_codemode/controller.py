"""Transport-neutral orchestration for one Code Mode execution."""

from __future__ import annotations

import json
from typing import Any, Callable, Mapping
import uuid

from .backend import BackendError, ExecutionBackend
from .protocol import (
    ExecutionRequest,
    RequestValidationError,
    SourceCompileError,
    error_envelope,
)


BackendFactory = Callable[[], ExecutionBackend]


def _default_backend_factory() -> ExecutionBackend:
    from .transport.rpyc import RPyCBackend

    return RPyCBackend()


class Controller:
    """Validate, execute, and verify one complete request."""

    def __init__(self, backend_factory: BackendFactory | None = None) -> None:
        self._backend_factory = backend_factory or _default_backend_factory

    def run(
        self,
        source: str,
        args: Mapping[str, Any] | None = None,
        instance: Mapping[str, Any] | None = None,
        policy: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        run_id = uuid.uuid4().hex
        try:
            request = ExecutionRequest.from_inputs(
                source,
                args,
                instance,
                policy,
                run_id=run_id,
            )
            request.compile()
        except SourceCompileError as exc:
            return error_envelope(
                category="compile",
                error_type=type(exc).__name__,
                message=str(exc),
                completion="not_started",
                run_id=run_id,
                details={"line": exc.lineno, "column": exc.offset, "text": exc.text},
            )
        except RequestValidationError as exc:
            return error_envelope(
                category="validation",
                error_type=type(exc).__name__,
                message=str(exc),
                completion="not_started",
                run_id=run_id,
            )

        try:
            response_json = self._backend_factory().execute_json(
                request.to_json(),
                request.instance,
                request.policy.wait_timeout_seconds,
            )
        except BackendError as exc:
            return error_envelope(
                category=exc.category,
                error_type=exc.error_type,
                message=str(exc),
                completion=exc.completion,
                run_id=run_id,
            )
        except Exception as exc:  # Defensive adapter boundary.
            return error_envelope(
                category="internal",
                error_type=type(exc).__name__,
                message=f"Unexpected backend failure: {exc}",
                completion="unknown",
                run_id=run_id,
            )

        if not isinstance(response_json, str):
            return error_envelope(
                category="internal",
                error_type="InvalidBackendResponse",
                message="Houdini backend did not return a JSON string",
                completion="unknown",
                run_id=run_id,
            )
        response_size = len(response_json.encode("utf-8"))
        if response_size > request.policy.max_response_bytes:
            return error_envelope(
                category="result",
                error_type="ResponseTooLarge",
                message=(
                    f"Houdini response used {response_size} bytes, exceeding the "
                    f"{request.policy.max_response_bytes}-byte response limit"
                ),
                completion="complete",
                run_id=run_id,
            )
        try:
            response = json.loads(response_json)
        except json.JSONDecodeError as exc:
            return error_envelope(
                category="internal",
                error_type="InvalidBackendJSON",
                message=f"Houdini backend returned invalid JSON: {exc}",
                completion="unknown",
                run_id=run_id,
            )
        if not isinstance(response, dict) or not isinstance(response.get("ok"), bool):
            return error_envelope(
                category="internal",
                error_type="InvalidBackendEnvelope",
                message="Houdini backend returned an invalid response envelope",
                completion="unknown",
                run_id=run_id,
            )
        response_run_id = response.get("meta", {}).get("run_id")
        if response_run_id != run_id:
            return error_envelope(
                category="internal",
                error_type="RunIdMismatch",
                message="Houdini backend response did not match the submitted run ID",
                completion="unknown",
                run_id=run_id,
            )
        return response

    def doctor(
        self,
        *,
        instance: Mapping[str, Any] | None = None,
        policy: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.run(
            "result.emit(ctx.session.info())",
            instance=instance,
            policy=policy,
        )
