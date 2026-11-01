"""Bounded, local CLI diagnostics without model turns or session changes."""

from __future__ import annotations

import math
import os
from pathlib import Path
import re
import selectors
import shutil
import subprocess
import sys
import tempfile
import time

from .adapters import Adapter
from .core import SessionError
from .runner_process import Cancellation, cancellation_signals, terminate_group


MAX_PROBE_OUTPUT_BYTES = 262144
MAX_PROBE_TIMEOUT = 10
PROBE_SESSION_ID = '11111111-2222-4333-8444-555555555555'
OPTION_DECLARATION = re.compile(
    r'^\s*(--?[A-Za-z][A-Za-z0-9_-]*(?:\s*[,|]\s*--?[A-Za-z][A-Za-z0-9_-]*)*)(?=[\s,=]|$)')
OPTION_TOKEN = re.compile(r'--?[A-Za-z][A-Za-z0-9_-]*')


def _declared_options(help_text: str) -> set[str]:
    """Read option declarations, excluding prose mentions and longer names."""
    result = set()
    for line in help_text.splitlines():
        declaration = OPTION_DECLARATION.match(line)
        if declaration:
            result.update(OPTION_TOKEN.findall(declaration.group(1)))
    return result


def _command_options(arguments: list[str]) -> set[str]:
    return {argument for argument in arguments if argument.startswith('-') and argument != '-'}


def _help_probes(kind: str, executable: str) -> list[tuple[str, list[str], set[str]]]:
    # The adapter remains the source of required options. The doctor only checks
    # advertised syntax; it cannot establish the behavior of configuration values.
    adapter = Adapter(kind, executable, model='doctor-placeholder')
    initial = adapter.command(Path('/doctor-work'), Path('/doctor-schema.json'))
    resumed = adapter.command(Path('/doctor-work'), Path('/doctor-schema.json'), PROBE_SESSION_ID)
    if kind == 'claude':
        return [('help', ['--help'], _command_options(initial[1:] + resumed[1:]))]
    initial_start = initial.index('exec')
    resume_start = resumed.index('exec')
    return [('help', ['--help'], _command_options(initial[1:initial_start])),
            ('exec_help', ['exec', '--help'], _command_options(initial[initial_start + 1:])),
            ('resume_help', ['exec', 'resume', '--help'], _command_options(resumed[resume_start + 2:]))]


def _probe(executable: str, arguments: list[str], directory: str,
           timeout: float, cancellation: Cancellation) -> tuple[dict, str]:
    """Drain both pipes with a shared bound and clean up only this child group."""
    process = None
    cleaned = False
    captured = {'stdout': bytearray(), 'stderr': bytearray()}
    captured_bytes = 0
    result = {'ok': False, 'code': 'probe_failed', 'message': 'Local CLI probe did not finish.'}
    try:
        if cancellation.requested:
            raise SessionError('interrupted', 'Diagnostics interrupted; remaining probes were skipped.')
        process = subprocess.Popen([executable, *arguments], cwd=directory,
                                   stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, start_new_session=True,
                                   env={**os.environ, 'NO_COLOR': '1', 'TERM': 'dumb'})
        deadline = time.monotonic() + timeout
        with selectors.DefaultSelector() as readable:
            for name, stream in (('stdout', process.stdout), ('stderr', process.stderr)):
                os.set_blocking(stream.fileno(), False)
                readable.register(stream, selectors.EVENT_READ, name)
            while readable.get_map() or process.poll() is None:
                if cancellation.requested:
                    raise SessionError('interrupted', 'Diagnostics interrupted; remaining probes were skipped.')
                if time.monotonic() >= deadline:
                    raise SessionError('probe_timeout', 'Local probe timed out; inspect the CLI installation and retry doctor.')
                if process.poll() is not None and not cleaned:
                    # A successful parent can leave descendants holding its pipes.
                    # Stop that owned group before waiting for the remaining EOFs.
                    terminate_group(process)
                    cleaned = True
                for key, _ in readable.select(min(0.05, max(0, deadline - time.monotonic()))):
                    chunk = os.read(key.fd, 8192)
                    if not chunk:
                        readable.unregister(key.fileobj)
                        continue
                    captured[key.data].extend(chunk)
                    captured_bytes += len(chunk)
                    if captured_bytes > MAX_PROBE_OUTPUT_BYTES:
                        raise SessionError('probe_output_limit', 'Local probe exceeded 256 KiB; inspect the CLI installation.')
        if process.returncode != 0:
            result = {'ok': False, 'code': 'probe_failed', 'exit_code': process.returncode,
                      'message': 'Local CLI probe exited unsuccessfully; inspect the CLI installation and retry doctor.'}
        else:
            result = {'ok': True, 'code': 'passed', 'message': 'Local CLI probe completed.'}
    except SessionError as error:
        result = {'ok': False, 'code': error.code, 'message': str(error)}
    except subprocess.TimeoutExpired:
        result = {'ok': False, 'code': 'probe_cleanup',
                  'message': f'Owned probe group cleanup timed out (PID {process.pid}); inspect local processes.'}
    except OSError:
        result = {'ok': False, 'code': 'probe_failed',
                  'message': 'Cannot execute or read the local CLI probe; check its executable path and permissions.'}
    finally:
        if process is not None:
            try:
                if not cleaned:
                    terminate_group(process)
            except (OSError, subprocess.TimeoutExpired):
                result = {'ok': False, 'code': 'probe_cleanup',
                          'message': f'Cannot confirm the owned probe group stopped (PID {process.pid}); inspect local processes.'}
            finally:
                for stream in (process.stdout, process.stderr):
                    if stream is not None:
                        stream.close()
    if not result['ok']:
        return result, ''  # Do not expose arbitrary private stderr in diagnostics.
    try:
        # Pipe reads may split a Unicode character. Decode each stream before
        # joining so an intervening stderr chunk cannot corrupt stdout bytes.
        return result, '\n'.join(captured[name].decode('utf-8') for name in ('stdout', 'stderr'))
    except UnicodeError:
        return {'ok': False, 'code': 'probe_output',
                'message': 'Local CLI probe returned non-UTF-8 output; check its installation.'}, ''


def _provider(kind: str, command: str, directory: str, timeout: float,
              cancellation: Cancellation, supported: bool) -> dict:
    result = {'ok': False, 'command': command, 'executable': None, 'version': None, 'checks': []}
    if not supported or cancellation.requested:
        result['checks'].append({'name': 'availability', 'ok': False,
                                 'code': 'interrupted' if cancellation.requested else 'unsupported_runtime',
                                 'message': 'Probe skipped; resolve the runtime issue or interruption and rerun doctor.'})
        return result
    executable = shutil.which(command)
    if executable is None:
        result['checks'].append({'name': 'availability', 'ok': False, 'code': 'not_found',
                                 'message': f'Install {kind} or pass --{kind}-command with an executable program path.'})
        return result
    result['executable'] = str(Path(executable).absolute())
    version_check, version = _probe(result['executable'], ['--version'], directory, timeout, cancellation)
    result['checks'].append({'name': 'version', **version_check})
    if not version_check['ok']:
        return result
    result['version'] = next((' '.join(line.split())[:200] for line in version.splitlines() if line.strip()), '')
    if not result['version']:
        result['checks'][-1].update(ok=False, code='probe_output',
                                    message='Version probe returned no version; check the CLI installation.')
        return result
    for name, arguments, required in _help_probes(kind, result['executable']):
        check, help_text = _probe(result['executable'], arguments, directory, timeout, cancellation)
        if check['ok']:
            missing = sorted(required - _declared_options(help_text))
            check.update(missing_flags=missing)
            if missing:
                check.update(ok=False, code='missing_flags',
                             message=f'Update {kind} to a CLI advertising these required options in this help scope.')
        result['checks'].append({'name': name, **check})
        if check['code'] in ('interrupted', 'probe_timeout', 'probe_output_limit', 'probe_cleanup'):
            break
    result['ok'] = all(check['ok'] for check in result['checks'])
    return result


def doctor(*, codex_command: str = 'codex', claude_command: str = 'claude',
           probe_timeout: float = 5) -> dict:
    """Describe local prerequisites; no credentials, sessions, or model calls."""
    if not math.isfinite(probe_timeout) or not 0 < probe_timeout <= MAX_PROBE_TIMEOUT:
        raise SessionError('invalid_argument', '--probe-timeout must be finite, positive, and at most 10 seconds.')
    for kind, command in (('codex', codex_command), ('claude', claude_command)):
        if (not isinstance(command, str) or not command.strip() or command.startswith('-')
                or any(character in command for character in ('\x00', '\n', '\r'))
                or (any(character.isspace() for character in command) and shutil.which(command) is None)):
            raise SessionError('invalid_argument', f'--{kind}-command must name one executable program or path, without shell syntax or flags.')
    runtime = {
        'python': {'ok': sys.version_info[:2] >= (3, 11),
                   'version': '.'.join(str(part) for part in sys.version_info[:3]),
                   'message': 'Python 3.11 or later is required.'},
        'platform': {'ok': os.name == 'posix', 'name': sys.platform,
                     'message': 'A POSIX host (macOS, Linux, or WSL) is required; native Windows is unsupported.'},
    }
    supported = all(check['ok'] for check in runtime.values())
    with tempfile.TemporaryDirectory(prefix='agent-review-doctor-') as directory:
        with cancellation_signals() as cancellation:
            providers = {kind: _provider(kind, command, directory, probe_timeout, cancellation, supported)
                         for kind, command in (('codex', codex_command), ('claude', claude_command))}
    passed = supported and all(provider['ok'] for provider in providers.values())
    return {'ok': passed, 'local_checks_passed': passed, 'runtime': runtime, 'providers': providers,
            'authentication': 'not_checked',
            'limits': {'probe_timeout_seconds': probe_timeout, 'max_probe_output_bytes': MAX_PROBE_OUTPUT_BYTES},
            'limitations': [
                'Passing local checks does not guarantee authentication, provider access, effective restriction settings, successful model turns, or review quality.',
                'Help advertises option names; it does not verify configuration values or disabled-feature behavior. Installed CLIs and managed settings remain trusted.',
            ]}
