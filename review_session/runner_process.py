"""Bounded local subprocess groups; never retry a model invocation."""

from __future__ import annotations

from contextlib import contextmanager, ExitStack
from dataclasses import dataclass
import os
from pathlib import Path
import signal
import subprocess
import threading
import time
from typing import Callable, Iterator

from .core import SessionError


MAX_OUTPUT_BYTES = 4194304
POLL_SECONDS = 0.05


@contextmanager
def cancellation_signals() -> Iterator[Cancellation]:
    """Translate planned termination into cleanup on the main thread."""
    cancellation = Cancellation()
    if threading.current_thread() is not threading.main_thread():
        yield cancellation
        return
    def interrupt(signum, frame):
        cancellation.requested = True
    previous = {item: signal.getsignal(item) for item in (signal.SIGINT, signal.SIGTERM)}
    try:
        for item in previous:
            signal.signal(item, interrupt)
        yield cancellation
    finally:
        for item, handler in previous.items():
            signal.signal(item, handler)


@dataclass
class Cancellation:
    # Signal handlers set a flag so cancellation cannot interrupt Popen before
    # ownership is registered. The child inherits normal signal delivery.
    requested: bool = False


@dataclass
class Invocation:
    identifier: str
    command: list[str]
    directory: Path
    prompt: Path
    stdout: Path
    stderr: Path


def terminate_group(process: subprocess.Popen) -> None:
    # Only processes launched in this invocation are eligible. Persisted PIDs
    # from an interrupted coordinator are evidence, never targets for signals.
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=0.3)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait(timeout=2)


def execute(invocations: list[Invocation], timeout: float, check_open: Callable[[], None],
            started: Callable[[str, int], None], completed: Callable[[str, str], None]) -> None:
    """Run independent initial turns together, or one later turn at a time."""
    processes: dict[str, tuple[subprocess.Popen, Invocation, float, object, object]] = {}
    with ExitStack() as files:
        try:
            for invocation in invocations:
                check_open()
                source = files.enter_context(invocation.prompt.open('rb'))
                output = files.enter_context(os.fdopen(os.open(invocation.stdout, os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                                                               0o600), 'wb'))
                errors = files.enter_context(os.fdopen(os.open(invocation.stderr, os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                                                               0o600), 'wb'))
                try:
                    process = subprocess.Popen(invocation.command, cwd=invocation.directory,
                                               stdin=source, stdout=output, stderr=errors,
                                               start_new_session=True)
                    processes[invocation.identifier] = (process, invocation, time.monotonic(), output, errors)
                except OSError as error:
                    raise SessionError('runner_provider', f'Cannot start agent CLI: {error}') from None
                started(invocation.identifier, process.pid)
            while processes:
                check_open()
                for identifier, (process, invocation, began, output, errors) in list(processes.items()):
                    if invocation.stdout.stat().st_size > MAX_OUTPUT_BYTES or invocation.stderr.stat().st_size > MAX_OUTPUT_BYTES:
                        raise SessionError('runner_output_limit', 'Agent output exceeded 4 MiB; inspect private logs.')
                    if time.monotonic() - began >= timeout:
                        raise SessionError('runner_timeout', 'Agent turn exceeded --turn-timeout; partial work was preserved.')
                    code = process.poll()
                    if code is None:
                        continue
                    if code != 0:
                        raise SessionError('runner_provider', f'Agent CLI exited with status {code}; inspect private stderr.log.')
                    check_open()
                    terminate_group(process)
                    os.fsync(output.fileno())
                    os.fsync(errors.fileno())
                    if invocation.stderr.stat().st_size > MAX_OUTPUT_BYTES:
                        raise SessionError('runner_output_limit', 'Agent output exceeded 4 MiB; inspect private logs.')
                    try:
                        with invocation.stdout.open('rb') as handle:
                            raw = handle.read(MAX_OUTPUT_BYTES + 1)
                        if len(raw) > MAX_OUTPUT_BYTES:
                            raise SessionError('runner_output_limit', 'Agent output exceeded 4 MiB; inspect private logs.')
                        text = raw.decode('utf-8')
                    except UnicodeError:
                        raise SessionError('runner_response', 'Agent returned non-UTF-8 output.') from None
                    completed(identifier, text)
                    del processes[identifier]
                if processes:
                    time.sleep(POLL_SECONDS)
        finally:
            for process, _, _, _, _ in processes.values():
                terminate_group(process)
