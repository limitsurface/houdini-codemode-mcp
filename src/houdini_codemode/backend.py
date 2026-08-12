"""Transport-neutral execution backend contract."""

from __future__ import annotations

from typing import Protocol

from .protocol import InstanceConfig


class BackendError(RuntimeError):
    """A backend failure that can be represented by the public protocol."""

    category = "internal"
    completion = "unknown"

    def __init__(self, message: str, *, error_type: str | None = None) -> None:
        super().__init__(message)
        self.error_type = error_type or type(self).__name__


class BackendBusyError(BackendError):
    category = "busy"
    completion = "not_started"


class BackendConnectionError(BackendError):
    category = "connection"
    completion = "not_started"


class BackendWaitTimeoutError(BackendError):
    category = "timeout"
    completion = "unknown"


class BackendProtocolError(BackendError):
    category = "internal"
    completion = "unknown"


class ExecutionBackend(Protocol):
    """Send one request JSON value and return one response JSON value."""

    def execute_json(
        self,
        request_json: str,
        instance: InstanceConfig,
        wait_timeout_seconds: float,
    ) -> str: ...
