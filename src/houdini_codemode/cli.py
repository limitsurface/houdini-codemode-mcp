"""Operator and test CLI for Houdini Code Mode."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Sequence

from .controller import Controller
from .protocol import check_source, compact_json, error_envelope


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
        else:  # pragma: no cover - argparse enforces the command set.
            raise AssertionError(f"Unknown command: {namespace.command}")
    except (OSError, UnicodeError, ValueError) as exc:
        response = _validation_failure(exc)
    sys.stdout.write(compact_json(response) + "\n")
    return 0 if response.get("ok") is True else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
