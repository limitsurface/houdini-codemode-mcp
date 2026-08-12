"""Host-side transfer of a Houdini node between two local Code Mode sessions.

This is deliberately orchestration rather than a runtime extension: each
endpoint executes its existing bounded ``ctx.artifacts`` operation under its
own transport gate.  The artifact is only a same-host hand-off and is removed
before this call reports success.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any, Callable, Mapping
import uuid

from .controller import Controller
from .protocol import InstanceConfig, RequestValidationError


DEFAULT_MAX_ARTIFACT_BYTES = 64 * 1024 * 1024
_MIN_ARTIFACT_BYTES = 1024
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


class NodeTransferError(RuntimeError):
    """A cross-session transfer could not complete safely."""


@dataclass(frozen=True, slots=True)
class TransferEndpoint:
    """An explicitly addressed trusted-local Houdini endpoint."""

    host: str
    port: int

    @classmethod
    def from_value(cls, value: Mapping[str, Any], *, label: str) -> "TransferEndpoint":
        if not isinstance(value, Mapping):
            raise NodeTransferError(f"{label} must be an endpoint object")
        if "port" not in value:
            raise NodeTransferError(f"{label}.port must be explicit")
        try:
            instance = InstanceConfig.from_value(value)
        except RequestValidationError as exc:
            raise NodeTransferError(f"Invalid {label}: {exc}") from exc
        return cls(instance.host, instance.port)

    def to_instance(self) -> dict[str, Any]:
        return {"host": self.host, "port": self.port}


ControllerFactory = Callable[[], Controller]


_EXPORT_SOURCE = """artifact = ctx.artifacts.export_node(
    args['node_path'],
    name=args['artifact_name'],
    children=args['children'],
    all_parms=args['all_parms'],
    editables=args['editables'],
    overwrite=False,
    max_bytes=args['max_bytes'],
)
result.emit({
    'artifact': artifact['artifact'],
    'source': artifact['source'],
    'capture': artifact['capture'],
    'summary': artifact['summary'],
})
"""

_IMPORT_SOURCE = """restored = ctx.artifacts.import_node(
    args['artifact_reference'],
    args['parent_path'],
    name=args['name'],
    unique=args['unique'],
    max_bytes=args['max_bytes'],
)
result.emit(restored)
"""

_REMOVE_SOURCE = "result.emit(ctx.artifacts.remove(args['artifact_reference']))"
_ROOT_SOURCE = "result.emit(ctx.artifacts.root())"


def _bounded_text(value: Any, maximum: int = 500) -> str:
    text = str(value).strip() or type(value).__name__
    return text if len(text) <= maximum else text[: maximum - 3] + "..."


def _required_text(value: str, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise NodeTransferError(f"{label} must be a non-empty string")
    return value


def _artifact_limit(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise NodeTransferError("max_artifact_bytes must be an integer")
    if not _MIN_ARTIFACT_BYTES <= value <= DEFAULT_MAX_ARTIFACT_BYTES:
        raise NodeTransferError(
            "max_artifact_bytes must be from "
            f"{_MIN_ARTIFACT_BYTES} to {DEFAULT_MAX_ARTIFACT_BYTES}"
        )
    return value


def _response_value(response: Any, *, operation: str) -> dict[str, Any]:
    if not isinstance(response, Mapping):
        raise NodeTransferError(f"{operation} returned an invalid controller response")
    if response.get("ok") is not True:
        error = response.get("error")
        if isinstance(error, Mapping):
            message = error.get("message") or error.get("type")
        else:
            message = error
        raise NodeTransferError(f"{operation} failed: {_bounded_text(message)}")
    data = response.get("data")
    value = data.get("value") if isinstance(data, Mapping) else None
    if not isinstance(value, dict):
        raise NodeTransferError(f"{operation} returned an invalid result")
    return dict(value)


def _run(
    controller_factory: ControllerFactory,
    endpoint: TransferEndpoint,
    source: str,
    args: Mapping[str, Any],
    *,
    label: str,
) -> dict[str, Any]:
    response = controller_factory().run(
        source,
        args=args,
        instance=endpoint.to_instance(),
        policy={"label": label, "undo_group": True},
    )
    return _response_value(response, operation=label)


def _cleanup(
    controller_factory: ControllerFactory,
    endpoint: TransferEndpoint,
    artifact_reference: str,
) -> tuple[dict[str, Any], str | None]:
    try:
        label = "Houdini Code Mode transfer artifact cleanup"
        response = controller_factory().run(
            _REMOVE_SOURCE,
            args={"artifact_reference": artifact_reference},
            instance=endpoint.to_instance(),
            policy={"label": label, "undo_group": True},
        )
        if isinstance(response, Mapping) and response.get("ok") is not True:
            error = response.get("error")
            if isinstance(error, Mapping) and error.get("type") == "FileNotFoundError":
                return {
                    "host": endpoint.host,
                    "port": endpoint.port,
                    "result": {"removed": False, "already_absent": True},
                }, None
        value = _response_value(response, operation=label)
        return {"host": endpoint.host, "port": endpoint.port, "result": value}, None
    except Exception as exc:
        return {"host": endpoint.host, "port": endpoint.port}, _bounded_text(exc)


def _artifact_root(
    controller_factory: ControllerFactory, endpoint: TransferEndpoint, maximum: int
) -> str:
    value = _run(
        controller_factory,
        endpoint,
        _ROOT_SOURCE,
        {},
        label="Houdini Code Mode transfer artifact-root check",
    )
    path = value.get("path")
    supported = value.get("max_bytes")
    if not isinstance(path, str) or not path:
        raise NodeTransferError("artifact-root check returned no path")
    if isinstance(supported, bool) or not isinstance(supported, int) or supported < maximum:
        raise NodeTransferError("artifact-root check does not support the requested byte limit")
    return os.path.normcase(os.path.normpath(path))


def transfer_node(
    node_path: str,
    destination_parent: str,
    *,
    source: Mapping[str, Any],
    destination: Mapping[str, Any],
    name: str | None = None,
    unique: bool = False,
    children: bool = True,
    all_parms: bool = False,
    editables: bool = False,
    max_artifact_bytes: int = DEFAULT_MAX_ARTIFACT_BYTES,
    controller_factory: ControllerFactory = Controller,
) -> dict[str, Any]:
    """Restore ``node_path`` under ``destination_parent`` in another session.

    Both endpoint mappings must supply a port and must name distinct loopback
    endpoints.  The source artifact name is generated per call, and its
    manifest is validated before import.  No HIP save operation is issued.
    """

    node_path = _required_text(node_path, label="node_path")
    destination_parent = _required_text(destination_parent, label="destination_parent")
    if name is not None:
        _required_text(name, label="name")
    for value, label in ((unique, "unique"), (children, "children"), (all_parms, "all_parms"), (editables, "editables")):
        if not isinstance(value, bool):
            raise NodeTransferError(f"{label} must be a boolean")
    maximum = _artifact_limit(max_artifact_bytes)
    source_endpoint = TransferEndpoint.from_value(source, label="source")
    destination_endpoint = TransferEndpoint.from_value(destination, label="destination")
    if source_endpoint.host not in _LOOPBACK_HOSTS or destination_endpoint.host not in _LOOPBACK_HOSTS:
        raise NodeTransferError("transfer requires trusted local loopback endpoints")
    if source_endpoint.port == destination_endpoint.port:
        raise NodeTransferError("transfer requires distinct source and destination ports")

    source_root = _artifact_root(controller_factory, source_endpoint, maximum)
    destination_root = _artifact_root(controller_factory, destination_endpoint, maximum)
    if source_root != destination_root:
        raise NodeTransferError(
            "source and destination must use the same artifact root for transfer"
        )

    artifact_name = "hcm-xfer-" + uuid.uuid4().hex
    artifact_reference: str | None = None
    exported: dict[str, Any] | None = None
    imported: dict[str, Any] | None = None
    primary_error: Exception | None = None
    cleanup: list[dict[str, Any]] = []
    cleanup_errors: list[str] = []
    try:
        exported = _run(
            controller_factory,
            source_endpoint,
            _EXPORT_SOURCE,
            {
                "node_path": node_path,
                "artifact_name": artifact_name,
                "children": children,
                "all_parms": all_parms,
                "editables": editables,
                "max_bytes": maximum,
            },
            label="Houdini Code Mode transfer export",
        )
        manifest = exported.get("artifact")
        if not isinstance(manifest, Mapping):
            raise NodeTransferError("export returned no artifact manifest")
        candidate = manifest.get("path")
        if not isinstance(candidate, str) or not candidate:
            raise NodeTransferError("export artifact manifest has no path")
        size = manifest.get("bytes")
        if isinstance(size, bool) or not isinstance(size, int) or not 0 <= size <= maximum:
            raise NodeTransferError("export artifact manifest exceeds its byte limit")
        artifact_reference = candidate
        imported = _run(
            controller_factory,
            destination_endpoint,
            _IMPORT_SOURCE,
            {
                "artifact_reference": artifact_reference,
                "parent_path": destination_parent,
                "name": name,
                "unique": unique,
                "max_bytes": maximum,
            },
            label="Houdini Code Mode transfer import",
        )
    except Exception as exc:
        primary_error = exc
    finally:
        if artifact_reference is not None:
            # Source removal owns the artifact.  The destination attempt proves
            # that its artifact view is also clean (normally ``removed=False``
            # because both sessions share this same-host file).
            for endpoint in (source_endpoint, destination_endpoint):
                status, cleanup_error = _cleanup(
                    controller_factory, endpoint, artifact_reference
                )
                cleanup.append(status)
                if cleanup_error is not None:
                    cleanup_errors.append(
                        f"{endpoint.host}:{endpoint.port}: {cleanup_error}"
                    )

    if primary_error is not None:
        if cleanup_errors:
            raise NodeTransferError(
                f"{_bounded_text(primary_error)}; cleanup failed: "
                + "; ".join(cleanup_errors)
            ) from primary_error
        raise primary_error
    assert exported is not None and imported is not None  # Narrowing for callers.
    manifest = exported["artifact"]
    return {
        "operation": "transfer",
        "source": {
            "host": source_endpoint.host,
            "port": source_endpoint.port,
            "path": node_path,
            "summary": exported.get("summary"),
            "hip_saved": False,
        },
        "destination": {
            "host": destination_endpoint.host,
            "port": destination_endpoint.port,
            "path": imported.get("path"),
            "type": imported.get("type"),
            "verified": imported.get("verified"),
            "summary": imported.get("destination_summary"),
            "error_count": imported.get("error_count"),
            "warning_count": imported.get("warning_count"),
            "hip_saved": False,
        },
        "capture": exported.get("capture"),
        "artifact": {
            key: manifest[key]
            for key in ("id", "bytes", "sha256", "schema", "schema_version")
            if key in manifest
        },
        "cleanup": cleanup,
        "cleanup_complete": not cleanup_errors,
        "cleanup_errors": cleanup_errors,
        "effects": {
            "source_hip_saved": False,
            "destination_hip_saved": False,
        },
    }
