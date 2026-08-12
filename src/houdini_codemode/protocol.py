"""Versioned public request and response primitives."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from typing import Any, Mapping
import uuid


PROTOCOL_VERSION = "0.1"
RUNTIME_VERSION = "0.2"

MAX_SOURCE_BYTES = 256 * 1024
MAX_ARGS_BYTES = 256 * 1024

DEFAULT_WAIT_TIMEOUT_SECONDS = 60.0
DEFAULT_MAX_LOG_BYTES = 32 * 1024
DEFAULT_MAX_RESULT_BYTES = 256 * 1024
DEFAULT_MAX_RESPONSE_BYTES = 512 * 1024
DEFAULT_MAX_STRING_BYTES = 64 * 1024
DEFAULT_MAX_CONTAINER_ITEMS = 1_000
DEFAULT_MAX_TOTAL_ITEMS = 10_000
DEFAULT_MAX_DEPTH = 12

HARD_MAX_WAIT_TIMEOUT_SECONDS = 600.0
HARD_MAX_LOG_BYTES = 256 * 1024
HARD_MAX_RESULT_BYTES = 1024 * 1024
HARD_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
HARD_MAX_STRING_BYTES = 256 * 1024
HARD_MAX_CONTAINER_ITEMS = 10_000
HARD_MAX_TOTAL_ITEMS = 100_000
HARD_MAX_DEPTH = 64


class RequestValidationError(ValueError):
    """The caller supplied an invalid execution request."""


class SourceCompileError(RequestValidationError):
    """The submitted source is not valid Python."""

    def __init__(self, exc: SyntaxError) -> None:
        message = exc.msg or "Invalid Python source"
        if exc.lineno is not None:
            message = f"{message} (line {exc.lineno}, column {exc.offset or 0})"
        super().__init__(message)
        self.lineno = exc.lineno
        self.offset = exc.offset
        self.text = exc.text.rstrip("\r\n") if exc.text else None


def compact_json(value: Any) -> str:
    """Serialize deterministic UTF-8 JSON and reject non-finite floats."""
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _trim_utf8(value: str, maximum: int) -> str:
    encoded = value.encode("utf-8", errors="replace")
    if len(encoded) <= maximum:
        return value
    return encoded[:maximum].decode("utf-8", errors="ignore")


def _json_object(value: Mapping[str, Any] | None, *, label: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise RequestValidationError(f"{label} must be a JSON object")
    try:
        _validate_json_value(dict(value), path=label, active=set())
        normalized = json.loads(compact_json(dict(value)))
    except (TypeError, ValueError) as exc:
        raise RequestValidationError(f"{label} must contain only finite JSON values: {exc}") from exc
    if not isinstance(normalized, dict):
        raise RequestValidationError(f"{label} must be a JSON object")
    return normalized


def _validate_json_value(value: Any, *, path: str, active: set[int]) -> None:
    if value is None or isinstance(value, (bool, int, str)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"non-finite float at {path}")
        return
    if isinstance(value, (list, tuple)):
        identity = id(value)
        if identity in active:
            raise ValueError(f"cycle at {path}")
        active.add(identity)
        try:
            for index, item in enumerate(value):
                _validate_json_value(item, path=f"{path}[{index}]", active=active)
        finally:
            active.remove(identity)
        return
    if isinstance(value, Mapping):
        identity = id(value)
        if identity in active:
            raise ValueError(f"cycle at {path}")
        active.add(identity)
        try:
            for key, item in value.items():
                if not isinstance(key, str):
                    raise ValueError(f"non-string object key at {path}")
                _validate_json_value(item, path=f"{path}.{key}", active=active)
        finally:
            active.remove(identity)
        return
    raise TypeError(f"unsupported {type(value).__name__} at {path}")


def _bounded_int(
    value: Any,
    *,
    name: str,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise RequestValidationError(f"{name} must be an integer")
    if value < minimum:
        raise RequestValidationError(f"{name} must be at least {minimum}")
    return min(value, maximum)


def _bounded_float(
    value: Any,
    *,
    name: str,
    default: float,
    minimum: float,
    maximum: float,
) -> float:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RequestValidationError(f"{name} must be a number")
    result = float(value)
    if not math.isfinite(result) or result < minimum:
        raise RequestValidationError(f"{name} must be finite and at least {minimum:g}")
    return min(result, maximum)


@dataclass(frozen=True, slots=True)
class InstanceConfig:
    host: str = "localhost"
    port: int = 18811

    @classmethod
    def from_value(cls, value: Mapping[str, Any] | None) -> "InstanceConfig":
        raw = _json_object(value, label="instance")
        unknown = set(raw) - {"host", "port"}
        if unknown:
            raise RequestValidationError(
                "Unknown instance fields: " + ", ".join(sorted(unknown))
            )
        host = raw.get("host", "localhost")
        port = raw.get("port", 18811)
        if not isinstance(host, str) or not host.strip():
            raise RequestValidationError("instance.host must be a non-empty string")
        if len(host.encode("utf-8")) > 255:
            raise RequestValidationError("instance.host is too long")
        host = host.strip().lower()
        if host not in {"localhost", "127.0.0.1", "::1"}:
            raise RequestValidationError(
                "instance.host must be a loopback address in the trusted-local release"
            )
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise RequestValidationError("instance.port must be an integer from 1 to 65535")
        return cls(host=host, port=port)

    def to_dict(self) -> dict[str, Any]:
        return {"host": self.host, "port": self.port}


@dataclass(frozen=True, slots=True)
class ExecutionPolicy:
    wait_timeout_seconds: float = DEFAULT_WAIT_TIMEOUT_SECONDS
    max_log_bytes: int = DEFAULT_MAX_LOG_BYTES
    max_result_bytes: int = DEFAULT_MAX_RESULT_BYTES
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES
    max_string_bytes: int = DEFAULT_MAX_STRING_BYTES
    max_container_items: int = DEFAULT_MAX_CONTAINER_ITEMS
    max_total_items: int = DEFAULT_MAX_TOTAL_ITEMS
    max_depth: int = DEFAULT_MAX_DEPTH
    undo_group: bool = True
    label: str = "Houdini Code Mode"

    @classmethod
    def from_value(cls, value: Mapping[str, Any] | None) -> "ExecutionPolicy":
        raw = _json_object(value, label="policy")
        allowed = {
            "wait_timeout_seconds",
            "max_log_bytes",
            "max_result_bytes",
            "max_response_bytes",
            "max_string_bytes",
            "max_container_items",
            "max_total_items",
            "max_depth",
            "undo_group",
            "label",
        }
        unknown = set(raw) - allowed
        if unknown:
            raise RequestValidationError(
                "Unknown policy fields: " + ", ".join(sorted(unknown))
            )
        undo_group = raw.get("undo_group", True)
        if not isinstance(undo_group, bool):
            raise RequestValidationError("policy.undo_group must be a boolean")
        label = raw.get("label", "Houdini Code Mode")
        if not isinstance(label, str) or not label.strip():
            raise RequestValidationError("policy.label must be a non-empty string")
        if len(label.encode("utf-8")) > 128:
            raise RequestValidationError("policy.label must be at most 128 UTF-8 bytes")
        return cls(
            wait_timeout_seconds=_bounded_float(
                raw.get("wait_timeout_seconds"),
                name="policy.wait_timeout_seconds",
                default=DEFAULT_WAIT_TIMEOUT_SECONDS,
                minimum=0.1,
                maximum=HARD_MAX_WAIT_TIMEOUT_SECONDS,
            ),
            max_log_bytes=_bounded_int(
                raw.get("max_log_bytes"),
                name="policy.max_log_bytes",
                default=DEFAULT_MAX_LOG_BYTES,
                minimum=0,
                maximum=HARD_MAX_LOG_BYTES,
            ),
            max_result_bytes=_bounded_int(
                raw.get("max_result_bytes"),
                name="policy.max_result_bytes",
                default=DEFAULT_MAX_RESULT_BYTES,
                minimum=256,
                maximum=HARD_MAX_RESULT_BYTES,
            ),
            max_response_bytes=_bounded_int(
                raw.get("max_response_bytes"),
                name="policy.max_response_bytes",
                default=DEFAULT_MAX_RESPONSE_BYTES,
                minimum=1024,
                maximum=HARD_MAX_RESPONSE_BYTES,
            ),
            max_string_bytes=_bounded_int(
                raw.get("max_string_bytes"),
                name="policy.max_string_bytes",
                default=DEFAULT_MAX_STRING_BYTES,
                minimum=16,
                maximum=HARD_MAX_STRING_BYTES,
            ),
            max_container_items=_bounded_int(
                raw.get("max_container_items"),
                name="policy.max_container_items",
                default=DEFAULT_MAX_CONTAINER_ITEMS,
                minimum=1,
                maximum=HARD_MAX_CONTAINER_ITEMS,
            ),
            max_total_items=_bounded_int(
                raw.get("max_total_items"),
                name="policy.max_total_items",
                default=DEFAULT_MAX_TOTAL_ITEMS,
                minimum=1,
                maximum=HARD_MAX_TOTAL_ITEMS,
            ),
            max_depth=_bounded_int(
                raw.get("max_depth"),
                name="policy.max_depth",
                default=DEFAULT_MAX_DEPTH,
                minimum=1,
                maximum=HARD_MAX_DEPTH,
            ),
            undo_group=undo_group,
            label=label.strip(),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "wait_timeout_seconds": self.wait_timeout_seconds,
            "max_log_bytes": self.max_log_bytes,
            "max_result_bytes": self.max_result_bytes,
            "max_response_bytes": self.max_response_bytes,
            "max_string_bytes": self.max_string_bytes,
            "max_container_items": self.max_container_items,
            "max_total_items": self.max_total_items,
            "max_depth": self.max_depth,
            "undo_group": self.undo_group,
            "label": self.label,
        }


@dataclass(frozen=True, slots=True)
class ExecutionRequest:
    source: str
    args: dict[str, Any]
    instance: InstanceConfig
    policy: ExecutionPolicy
    run_id: str

    @classmethod
    def from_inputs(
        cls,
        source: str,
        args: Mapping[str, Any] | None = None,
        instance: Mapping[str, Any] | None = None,
        policy: Mapping[str, Any] | None = None,
        *,
        run_id: str | None = None,
    ) -> "ExecutionRequest":
        if not isinstance(source, str):
            raise RequestValidationError("source must be a string")
        if not source.strip():
            raise RequestValidationError("source must not be empty")
        if "\x00" in source:
            raise RequestValidationError("source must not contain NUL bytes")
        if len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
            raise RequestValidationError(
                f"source exceeds the {MAX_SOURCE_BYTES}-byte hard limit"
            )
        normalized_args = _json_object(args, label="args")
        if len(compact_json(normalized_args).encode("utf-8")) > MAX_ARGS_BYTES:
            raise RequestValidationError(
                f"args exceeds the {MAX_ARGS_BYTES}-byte hard limit"
            )
        return cls(
            source=source,
            args=normalized_args,
            instance=InstanceConfig.from_value(instance),
            policy=ExecutionPolicy.from_value(policy),
            run_id=run_id or uuid.uuid4().hex,
        )

    def compile(self) -> None:
        try:
            compile(self.source, "<houdini-codemode>", "exec")
        except SyntaxError as exc:
            raise SourceCompileError(exc) from exc

    def to_wire_dict(self) -> dict[str, Any]:
        return {
            "protocol_version": PROTOCOL_VERSION,
            "expected_runtime_version": RUNTIME_VERSION,
            "run_id": self.run_id,
            "source": self.source,
            "args": self.args,
            "policy": self.policy.to_dict(),
        }

    def to_json(self) -> str:
        return compact_json(self.to_wire_dict())


def error_envelope(
    *,
    category: str,
    error_type: str,
    message: str,
    completion: str,
    run_id: str | None = None,
    details: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    error: dict[str, Any] = {
        "category": category,
        "type": error_type,
        "message": _trim_utf8(message, 4096),
    }
    if details:
        error["details"] = dict(details)
    return {
        "ok": False,
        "error": error,
        "meta": {
            "run_id": run_id,
            "completion": completion,
            "protocol_version": PROTOCOL_VERSION,
            "runtime_version": RUNTIME_VERSION,
        },
    }


def check_source(source: str) -> dict[str, Any]:
    run_id = uuid.uuid4().hex
    try:
        request = ExecutionRequest.from_inputs(source, run_id=run_id)
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
    return {
        "ok": True,
        "data": {"valid": True},
        "meta": {
            "run_id": run_id,
            "completion": "not_started",
            "protocol_version": PROTOCOL_VERSION,
            "runtime_version": RUNTIME_VERSION,
        },
    }
