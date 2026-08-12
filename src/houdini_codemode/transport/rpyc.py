"""RPyC backend for a live Houdini hrpyc server."""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
import socket
import threading
from typing import Any, Iterator

import rpyc
from rpyc.core.async_ import AsyncResultTimeout
from rpyc.utils.classic import obtain

from ..backend import (
    BackendBusyError,
    BackendConnectionError,
    BackendProtocolError,
    BackendWaitTimeoutError,
)
from ..protocol import InstanceConfig
from ..protocol import RUNTIME_VERSION
from ..runtime_source import RUNTIME_SOURCE, RUNTIME_SOURCE_HASH
from .gate import ConnectionQueueTimeoutError, connection_gate


@dataclass(slots=True)
class RPyCBackend:
    connect_timeout_seconds: float = 5.0
    queue_timeout_seconds: float = 30.0

    @contextlib.contextmanager
    def _connect(
        self,
        instance: InstanceConfig,
        remote_timeout_seconds: float | None,
        on_admitted: Any | None = None,
    ) -> Iterator[Any]:
        try:
            gate = connection_gate(
                instance.host,
                instance.port,
                self.queue_timeout_seconds,
            )
            with gate:
                if on_admitted is not None:
                    on_admitted()
                previous_timeout = socket.getdefaulttimeout()
                socket.setdefaulttimeout(self.connect_timeout_seconds)
                try:
                    try:
                        connection = rpyc.classic.connect(instance.host, instance.port)
                    except (socket.timeout, ConnectionRefusedError, EOFError, OSError) as exc:
                        detail = str(exc).strip()
                        message = f"Failed to connect to Houdini at {instance.host}:{instance.port}"
                        if detail:
                            message += f": {detail}"
                        raise BackendConnectionError(message) from exc
                finally:
                    socket.setdefaulttimeout(previous_timeout)

                if hasattr(connection, "_config"):
                    connection._config["sync_request_timeout"] = remote_timeout_seconds
                try:
                    yield connection
                finally:
                    try:
                        connection.close()
                    except Exception:
                        pass
        except ConnectionQueueTimeoutError as exc:
            raise BackendBusyError(str(exc), error_type=type(exc).__name__) from exc

    def _execute_json_blocking(
        self,
        request_json: str,
        instance: InstanceConfig,
        on_admitted: Any,
    ) -> str:
        stage = "connect"
        try:
            with self._connect(instance, None, on_admitted) as connection:
                stage = "bootstrap"
                connection.execute("import hou as _hcm_bootstrap_hou")
                remote_hash = obtain(
                    connection.eval(
                        "getattr(_hcm_bootstrap_hou.session, "
                        "'_houdini_codemode_runtime_hash', None)"
                    )
                )
                remote_version = obtain(
                    connection.eval(
                        "getattr(_hcm_bootstrap_hou.session, "
                        "'_houdini_codemode_runtime_version', None)"
                    )
                )
                if remote_hash != RUNTIME_SOURCE_HASH or remote_version != RUNTIME_VERSION:
                    stage = "install"
                    connection.execute(RUNTIME_SOURCE)
                    connection.namespace["_houdini_codemode_install_hash"] = RUNTIME_SOURCE_HASH
                    connection.namespace["_houdini_codemode_install_version"] = RUNTIME_VERSION
                    connection.execute(
                        "_hcm_hou.session._houdini_codemode_runtime_hash = "
                        "_houdini_codemode_install_hash\n"
                        "_hcm_hou.session._houdini_codemode_runtime_version = "
                        "_houdini_codemode_install_version\n"
                        "_hcm_hou.session._houdini_codemode_execute_json = "
                        "_houdini_codemode_execute_json"
                    )
                stage = "execute"
                connection.namespace["_houdini_codemode_request_json"] = request_json
                remote = connection.eval(
                    "_hcm_bootstrap_hou.session._houdini_codemode_execute_json("
                    "_houdini_codemode_request_json)"
                )
                stage = "obtain"
                response = obtain(remote)
        except AsyncResultTimeout as exc:
            raise BackendWaitTimeoutError(
                "Stopped waiting for Houdini; remote execution may still be running",
                error_type="RemoteWaitTimeout",
            ) from exc
        except (BackendBusyError, BackendConnectionError):
            raise
        except (EOFError, OSError, socket.timeout) as exc:
            if stage == "connect":
                raise BackendConnectionError(
                    f"Failed to connect to Houdini at {instance.host}:{instance.port}: {exc}",
                    error_type=type(exc).__name__,
                ) from exc
            raise BackendProtocolError(
                f"Houdini connection was lost during {stage}: {exc}",
                error_type=type(exc).__name__,
            ) from exc
        except Exception as exc:
            raise BackendProtocolError(
                f"RPyC backend failed during {stage}: {exc}",
                error_type=type(exc).__name__,
            ) from exc
        if not isinstance(response, str):
            raise BackendProtocolError(
                "Houdini runtime did not return a JSON string",
                error_type="InvalidRemoteResponse",
            )
        return response

    def execute_json(
        self,
        request_json: str,
        instance: InstanceConfig,
        wait_timeout_seconds: float,
    ) -> str:
        """Execute while retaining the endpoint gate after a caller wait timeout.

        The RPyC connection lives entirely on a background waiter thread.  If the
        caller stops waiting, that thread keeps the connection and cross-process
        mutex until Houdini actually returns or the connection fails.  This does
        not cancel remote Python; it prevents a timed-out Code Mode request from
        immediately admitting overlapping local work.
        """

        admitted = threading.Event()
        finished = threading.Event()
        cancelled_before_admission = threading.Event()
        state: dict[str, Any] = {"admitted": False}

        def on_admitted() -> None:
            if cancelled_before_admission.is_set():
                raise BackendBusyError(
                    "Local Houdini admission was cancelled before execution started",
                    error_type="AdmissionCancelled",
                )
            state["admitted"] = True
            admitted.set()

        def wait_for_remote() -> None:
            try:
                state["response"] = self._execute_json_blocking(
                    request_json,
                    instance,
                    on_admitted,
                )
            except BaseException as exc:
                state["error"] = exc
            finally:
                admitted.set()
                finished.set()

        waiter = threading.Thread(
            target=wait_for_remote,
            name=f"houdini-codemode-waiter-{instance.host}-{instance.port}",
            daemon=True,
        )
        waiter.start()

        admission_wait = self.queue_timeout_seconds + 1.0
        if not admitted.wait(admission_wait):
            cancelled_before_admission.set()
            raise BackendBusyError(
                "Timed out waiting to enter the local Houdini connection queue",
                error_type="ConnectionQueueTimeoutError",
            )
        if not state["admitted"]:
            finished.wait()
            error = state.get("error")
            if isinstance(error, BaseException):
                raise error
            raise BackendProtocolError(
                "Houdini waiter ended before endpoint admission",
                error_type="WaiterAdmissionError",
            )
        if not finished.wait(wait_timeout_seconds):
            raise BackendWaitTimeoutError(
                "Stopped waiting for Houdini; the background waiter is retaining "
                "the endpoint gate until remote completion",
                error_type="RemoteWaitTimeout",
            )
        error = state.get("error")
        if isinstance(error, BaseException):
            raise error
        response = state.get("response")
        if not isinstance(response, str):
            raise BackendProtocolError(
                "Houdini waiter did not return a JSON string",
                error_type="InvalidWaiterResponse",
            )
        return response
