"""Operator and test CLI for Houdini Code Mode."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Sequence

from .controller import Controller
from .protocol import PROTOCOL_VERSION, RUNTIME_VERSION, check_source, compact_json, error_envelope
from .xfer import DEFAULT_MAX_ARTIFACT_BYTES, NodeTransferError, transfer_node


def _add_source_options(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--code", help="Inline Python source.")
    group.add_argument("--file", type=Path, help="Read UTF-8 Python source from a file.")
    group.add_argument(
        "--input",
        choices=["-"],
        help="Read UTF-8 Python source from stdin (use '-').",
    )


def _add_endpoint_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=18811)


def _add_policy_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--wait-timeout", type=float)
    parser.add_argument("--max-log-bytes", type=int)
    parser.add_argument("--max-result-bytes", type=int)
    parser.add_argument("--max-response-bytes", type=int)
    parser.add_argument("--max-string-bytes", type=int)
    parser.add_argument("--max-container-items", type=int)
    parser.add_argument("--max-total-items", type=int)
    parser.add_argument("--max-depth", type=int)
    parser.add_argument("--label")
    parser.add_argument(
        "--no-undo-group",
        action="store_true",
        help="Do not group Houdini undo history for this run.",
    )


def _add_xfer_capture_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--children", action="store_true", help="Capture recursive child contents.")
    parser.add_argument("--all-parms", action="store_true", help="Include default-valued parameters.")
    parser.add_argument("--editables", action="store_true", help="Capture editable asset contents.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="houdini-codemode",
        description="Execute one bounded Python/HOM program in a live trusted Houdini session.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    check_parser = subparsers.add_parser("check", help="Validate source without Houdini.")
    _add_source_options(check_parser)

    run_parser = subparsers.add_parser("run", help="Execute one program in Houdini.")
    _add_source_options(run_parser)
    _add_endpoint_options(run_parser)
    _add_policy_options(run_parser)
    run_parser.add_argument(
        "--args",
        default="{}",
        help="JSON object supplied to the program as args (default: {}).",
    )

    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Run a read-only endpoint/runtime/main-thread diagnostic.",
    )
    _add_endpoint_options(doctor_parser)
    _add_policy_options(doctor_parser)

    xfer_parser = subparsers.add_parser(
        "xfer",
        help="Transfer a node between two local Houdini sessions through a bounded artifact.",
    )
    xfer_commands = xfer_parser.add_subparsers(dest="xfer_command", required=True)
    copy_parser = xfer_commands.add_parser(
        "copy",
        help="Copy a node from one explicit local endpoint to another.",
    )
    copy_parser.add_argument("node_path", help="Source Houdini node path.")
    copy_parser.add_argument("--to-parent", required=True, help="Destination parent network path.")
    copy_parser.add_argument("--from-host", default="localhost", help="Source loopback host.")
    copy_parser.add_argument("--from-port", type=int, required=True, help="Source hrpyc port.")
    copy_parser.add_argument("--to-host", default="localhost", help="Destination loopback host.")
    copy_parser.add_argument("--to-port", type=int, required=True, help="Destination hrpyc port.")
    copy_parser.add_argument("--name", help="Restored root-node name.")
    copy_parser.add_argument("--unique", action="store_true", help="Allow a unique suffix on name conflicts.")
    _add_xfer_capture_options(copy_parser)
    copy_parser.add_argument(
        "--max-artifact-bytes",
        type=int,
        default=DEFAULT_MAX_ARTIFACT_BYTES,
        help=f"Maximum artifact size (default: {DEFAULT_MAX_ARTIFACT_BYTES}).",
    )
    return parser


def _read_source(namespace: argparse.Namespace) -> str:
    if namespace.code is not None:
        return namespace.code
    if namespace.file is not None:
        return namespace.file.read_text(encoding="utf-8")
    return sys.stdin.read()


def _parse_args_json(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"--args is not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("--args must decode to a JSON object")
    return value


def _instance(namespace: argparse.Namespace) -> dict[str, Any]:
    return {"host": namespace.host, "port": namespace.port}


def _policy(namespace: argparse.Namespace) -> dict[str, Any]:
    fields = {
        "wait_timeout_seconds": namespace.wait_timeout,
        "max_log_bytes": namespace.max_log_bytes,
        "max_result_bytes": namespace.max_result_bytes,
        "max_response_bytes": namespace.max_response_bytes,
        "max_string_bytes": namespace.max_string_bytes,
        "max_container_items": namespace.max_container_items,
        "max_total_items": namespace.max_total_items,
        "max_depth": namespace.max_depth,
        "label": namespace.label,
    }
    result = {key: value for key, value in fields.items() if value is not None}
    result["undo_group"] = not namespace.no_undo_group
    return result


def _validation_failure(exc: Exception) -> dict[str, Any]:
    return error_envelope(
        category="validation",
        error_type=type(exc).__name__,
        message=str(exc),
        completion="not_started",
    )


def _xfer_copy_validation(namespace: argparse.Namespace) -> None:
    loopback_hosts = {"localhost", "127.0.0.1", "::1"}
    for host, label in (
        (namespace.from_host, "--from-host"),
        (namespace.to_host, "--to-host"),
    ):
        if not isinstance(host, str) or host.strip().lower() not in loopback_hosts:
            raise ValueError(f"{label} must be a trusted local loopback address")
    for port, label in (
        (namespace.from_port, "--from-port"),
        (namespace.to_port, "--to-port"),
    ):
        if not 1 <= port <= 65535:
            raise ValueError(f"{label} must be an integer from 1 to 65535")
    if namespace.from_port == namespace.to_port:
        raise ValueError("--from-port and --to-port must be distinct")
    if namespace.name is not None and not namespace.name.strip():
        raise ValueError("--name must be a non-empty string")
    if not 1024 <= namespace.max_artifact_bytes <= DEFAULT_MAX_ARTIFACT_BYTES:
        raise ValueError(
            "--max-artifact-bytes must be from 1024 to "
            f"{DEFAULT_MAX_ARTIFACT_BYTES}"
        )


def _xfer_success(result: dict[str, Any]) -> dict[str, Any]:
    """Wrap a completed transfer, including a non-fatal cleanup warning."""
    return {
        "ok": True,
        "data": {"value": result},
        "meta": {
            "completion": "complete",
            "operation": "xfer.copy",
            "cleanup_complete": result.get("cleanup_complete") is True,
            "protocol_version": PROTOCOL_VERSION,
            "runtime_version": RUNTIME_VERSION,
        },
    }


def _xfer_operation_failure(exc: NodeTransferError) -> dict[str, Any]:
    """A transfer error can follow remote work, so its completion is unknown."""
    return error_envelope(
        category="operation",
        error_type=type(exc).__name__,
        message=str(exc),
        completion="unknown",
    )


def _handle_xfer_copy(namespace: argparse.Namespace) -> dict[str, Any]:
    _xfer_copy_validation(namespace)
    try:
        result = transfer_node(
            namespace.node_path,
            namespace.to_parent,
            source={"host": namespace.from_host, "port": namespace.from_port},
            destination={"host": namespace.to_host, "port": namespace.to_port},
            name=namespace.name,
            unique=namespace.unique,
            children=namespace.children,
            all_parms=namespace.all_parms,
            editables=namespace.editables,
            max_artifact_bytes=namespace.max_artifact_bytes,
        )
    except NodeTransferError as exc:
        return _xfer_operation_failure(exc)
    return _xfer_success(result)


def main(argv: Sequence[str] | None = None) -> int:
    namespace = build_parser().parse_args(argv)
    try:
        if namespace.command == "check":
            response = check_source(_read_source(namespace))
        elif namespace.command == "run":
            response = Controller().run(
                _read_source(namespace),
                args=_parse_args_json(namespace.args),
                instance=_instance(namespace),
                policy=_policy(namespace),
            )
        elif namespace.command == "doctor":
            response = Controller().doctor(
                instance=_instance(namespace),
                policy=_policy(namespace),
            )
        elif namespace.command == "xfer":
            if namespace.xfer_command == "copy":
                response = _handle_xfer_copy(namespace)
            else:  # pragma: no cover - argparse enforces the command set.
                raise AssertionError(f"Unknown xfer command: {namespace.xfer_command}")
        else:  # pragma: no cover - argparse enforces the command set.
            raise AssertionError(f"Unknown command: {namespace.command}")
    except (OSError, UnicodeError, ValueError) as exc:
        response = _validation_failure(exc)
    sys.stdout.write(compact_json(response) + "\n")
    return 0 if response.get("ok") is True else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
