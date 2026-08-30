"""Small cooperative cross-process lock for study state transitions."""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path

from nullbench.errors import IntegrityError

_ACTIVE_GUARD = threading.Lock()
_ACTIVE_LOCKS: dict[str, tuple[int, int, str]] = {}


def _write_all(descriptor: int, data: bytes) -> None:
    """Write a complete lock owner record or fail before claiming ownership."""
    offset = 0
    while offset < len(data):
        written = os.write(descriptor, data[offset:])
        if written <= 0:
            raise OSError("short write while creating lock owner record")
        offset += written


@contextmanager
def _directory_lock(
    root: Path,
    *,
    filename: str,
    resource: str,
    timeout: float = 30.0,
) -> Iterator[None]:
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise IntegrityError(
            f"could not prepare {resource} lock directory: {root}",
            hint="check that the path exists and is writable",
        ) from exc
    path = root / filename
    lock_key = str(path.resolve())
    token = uuid.uuid4().hex
    deadline = time.monotonic() + timeout
    process_id = os.getpid()
    thread_id = threading.get_ident()
    with _ACTIVE_GUARD:
        active = _ACTIVE_LOCKS.get(lock_key)
    if active is not None and active[:2] == (process_id, thread_id):
        raise IntegrityError(
            f"{resource} lock is already held by this thread: {root}",
            hint=f"nested {resource} writes are not allowed",
        )
    payload = json.dumps(
        {
            "token": token,
            "pid": process_id,
            "thread": thread_id,
            "created": time.time(),
        }
    )

    while True:
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise IntegrityError(
                    f"{resource} is busy: {root}",
                    hint=f"wait for the other nullbench writer, or remove a stale {filename}",
                ) from None
            time.sleep(0.05)
            continue
        except OSError as exc:
            raise IntegrityError(
                f"could not create {resource} lock: {path}",
                hint="check filesystem permissions and health",
            ) from exc
        else:
            try:
                _write_all(descriptor, payload.encode("utf-8"))
                os.fsync(descriptor)
                os.close(descriptor)
            except OSError as exc:
                # O_EXCL already created the path. Never strand an empty or
                # partial lock when its owner record could not be persisted.
                with suppress(OSError):
                    os.close(descriptor)
                with suppress(OSError):
                    path.unlink()
                raise IntegrityError(
                    f"could not persist {resource} lock owner record: {path}",
                    hint="check filesystem health; no lock ownership was claimed",
                ) from exc
            except BaseException:
                with suppress(OSError):
                    os.close(descriptor)
                with suppress(OSError):
                    path.unlink()
                raise
            with _ACTIVE_GUARD:
                _ACTIVE_LOCKS[lock_key] = (process_id, thread_id, token)
            break

    try:
        yield
    finally:
        cleanup_error: IntegrityError | None = None
        cleanup_deadline = time.monotonic() + 2.0
        try:
            while True:
                try:
                    current = json.loads(path.read_text(encoding="utf-8"))
                    if current.get("token") != token:
                        cleanup_error = IntegrityError(
                            f"{resource} lock ownership changed before release: {root}",
                            hint=f"do not replace {filename} while a writer is active",
                        )
                        break
                    path.unlink()
                    break
                except FileNotFoundError:
                    break
                except (json.JSONDecodeError, OSError) as exc:
                    if time.monotonic() >= cleanup_deadline:
                        cleanup_error = IntegrityError(
                            f"could not release {resource} lock: {root}",
                            hint=f"check and remove stale {filename} after confirming no writer is active",
                        )
                        cleanup_error.__cause__ = exc
                        break
                    time.sleep(0.01)
        finally:
            with _ACTIVE_GUARD:
                if _ACTIVE_LOCKS.get(lock_key) == (process_id, thread_id, token):
                    del _ACTIVE_LOCKS[lock_key]
        if cleanup_error is not None:
            raise cleanup_error


@contextmanager
def study_lock(
    root: Path,
    *,
    timeout: float = 30.0,
) -> Iterator[None]:
    """Serialize normal writers touching experiment, draws, or ledger state.

    The lock is an atomic-create protocol, so it works on Windows and POSIX
    without another dependency. It is a coordination boundary, not protection
    against an operator who deliberately ignores or deletes the lock.
    """
    with _directory_lock(
        root,
        filename=".nullbench.lock",
        resource="study",
        timeout=timeout,
    ):
        yield


@contextmanager
def vault_lock(
    root: Path,
    *,
    timeout: float = 30.0,
) -> Iterator[None]:
    """Serialize key rotation and receipt reads/writes in one vault."""
    with _directory_lock(
        root,
        filename=".nullbench-vault.lock",
        resource="vault",
        timeout=timeout,
    ):
        yield
