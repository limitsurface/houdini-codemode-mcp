"""Cross-process admission control for Houdini connections.

The mutex namespace deliberately matches houdini-cli v0.3.2 so the standalone
products do not normally overlap against one local Houdini endpoint.
"""

from __future__ import annotations

import contextlib
import ctypes
import hashlib
import os
from collections.abc import Iterator


class ConnectionQueueTimeoutError(TimeoutError):
    """The local Houdini connection queue did not advance in time."""


def mutex_name(host: str, port: int) -> str:
    endpoint = f"{host.lower()}:{port}".encode("utf-8")
    digest = hashlib.sha256(endpoint).hexdigest()[:16]
    return f"Local\\houdini-cli-{digest}"


@contextlib.contextmanager
def connection_gate(host: str, port: int, timeout_seconds: float) -> Iterator[None]:
    """Allow only one local process at a time to connect to an endpoint."""
    if os.name != "nt":
        yield
        return

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_mutex = kernel32.CreateMutexW
    create_mutex.argtypes = (ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p)
    create_mutex.restype = ctypes.c_void_p
    wait_for_single_object = kernel32.WaitForSingleObject
    wait_for_single_object.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
    wait_for_single_object.restype = ctypes.c_uint32
    release_mutex = kernel32.ReleaseMutex
    release_mutex.argtypes = (ctypes.c_void_p,)
    release_mutex.restype = ctypes.c_bool
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (ctypes.c_void_p,)
    close_handle.restype = ctypes.c_bool

    handle = create_mutex(None, False, mutex_name(host, port))
    if not handle:
        raise OSError(ctypes.get_last_error(), "Failed to create Houdini connection mutex")

    wait_object_0 = 0x00000000
    wait_abandoned = 0x00000080
    wait_timeout = 0x00000102
    wait_failed = 0xFFFFFFFF
    timeout_ms = min(round(timeout_seconds * 1000), 0xFFFFFFFE)
    acquired = False
    try:
        result = wait_for_single_object(handle, timeout_ms)
        if result in (wait_object_0, wait_abandoned):
            acquired = True
            yield
            return
        if result == wait_timeout:
            raise ConnectionQueueTimeoutError(
                f"Timed out after {timeout_seconds:g}s waiting for the local Houdini connection queue"
            )
        if result == wait_failed:
            raise OSError(ctypes.get_last_error(), "Failed while waiting for Houdini connection mutex")
        raise OSError(f"Unexpected mutex wait result: {result}")
    finally:
        if acquired:
            release_mutex(handle)
        close_handle(handle)
