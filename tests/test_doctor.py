"""Local capability diagnostics through synthetic CLIs; no provider requests."""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from review_session.cli import main


CODEX_ROOT = """Options:
  --no-daemon
  --sandbox <MODE>
  --ask-for-approval <POLICY>
  --cd <DIR>
  --disable <FEATURE>
  -c, --config <KEY=VALUE>
"""
CODEX_EXEC = """Options:
  --json
  --ignore-user-config
  --ignore-rules
  --skip-git-repo-check
  --output-schema <FILE>
  -m, --model <MODEL>
"""
CLAUDE_HELP = """Options:
  -p, --print
  --output-format <FORMAT>
  --json-schema <SCHEMA>
  --tools <TOOLS>
  --append-system-prompt <PROMPT>
  --system-prompt-snapshot <MODE>
  --safe-mode
  --restricted
  --strict-mcp-config
  --mcp-config <CONFIG>
  --disallowedTools <TOOLS>
  --setting-sources <SOURCES>
  --settings <SETTINGS>
  --disable-slash-commands
  --no-chrome
  --permission-mode <MODE>
  --permission-prompts <MODE>
  --model <MODEL>
  --resume <SESSION>
"""

FAKE_CLI = r'''
import json, os, pathlib, subprocess, sys, time
root = pathlib.Path(__file__).parent
kind = 'codex' if 'codex' in pathlib.Path(__file__).name else 'claude'
config = json.loads((root / 'fixture.json').read_text())
arguments = sys.argv[1:]
with (root / 'calls.jsonl').open('a') as handle:
    handle.write(json.dumps({'kind': kind, 'arguments': arguments,
                             'cwd_files': os.listdir('.'), 'stdin': sys.stdin.read()}) + '\n')
allowed = [['--version'], ['--help']]
if kind == 'codex':
    allowed += [['exec', '--help'], ['exec', 'resume', '--help']]
if arguments not in allowed:
    sys.exit(99)  # A model invocation is never allowed in these tests.
case = config.get(kind + '_case', '')
if arguments == ['--version'] and case in ('hang', 'background', 'flood', 'nonzero'):
    if case in ('hang', 'background'):
        subprocess.Popen([sys.executable, '-c',
            'import pathlib,time; time.sleep(0.6); pathlib.Path(' + repr(str(root / 'child-survived')) + ').touch()'])
        if case == 'hang':
            time.sleep(30)
    elif case == 'flood':
        while True:
            os.write(1, b'x' * 8192)
            os.write(2, b'y' * 8192)
    elif case == 'nonzero':
        print('SYNTHETIC_PRIVATE_DIAGNOSTIC', file=sys.stderr)
        sys.exit(7)
if arguments == ['--version']:
    if case == 'unicode':
        os.write(1, b'codex synthetic \xe2')
        time.sleep(0.04)
        os.write(2, b'Benign local warning\n')
        time.sleep(0.04)
        os.write(1, b'\x80\x93 1.2.3\n')
        sys.exit(0)
    print(kind + ' synthetic 1.2.3')
else:
    key = kind + '_' + ('root' if arguments == ['--help'] else 'resume' if 'resume' in arguments else 'exec')
    print(config[key])
'''


class DoctorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.config = {'codex_root': CODEX_ROOT, 'codex_exec': CODEX_EXEC,
                       'codex_resume': CODEX_EXEC, 'claude_root': CLAUDE_HELP}
        for name in ('fake_codex', 'fake_claude'):
            path = self.root / name
            path.write_text('#!' + sys.executable + '\n' + FAKE_CLI)
            path.chmod(0o700)

    def arguments(self, *extra):
        return ['doctor', '--codex-command', str(self.root / 'fake_codex'),
                '--claude-command', str(self.root / 'fake_claude'), *extra]

    def write_fixture(self):
        (self.root / 'fixture.json').write_text(json.dumps(self.config))

    def command(self, *extra, passed=True):
        self.write_fixture()
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(self.arguments(*extra))
        self.assertEqual(stderr.getvalue(), '')
        result = json.loads(stdout.getvalue())
        self.assertEqual(code, 0 if result['local_checks_passed'] else 2, result)
        self.assertEqual(result['ok'], result['local_checks_passed'])
        if passed is not None:
            self.assertEqual(result['local_checks_passed'], passed, result)
        self.assertEqual(result['authentication'], 'not_checked')
        return result

    def calls(self):
        path = self.root / 'calls.jsonl'
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def test_success_checks_both_initial_and_resume_capabilities_without_tasks(self):
        result = self.command()
        self.assertEqual(result['providers']['codex']['version'], 'codex synthetic 1.2.3')
        self.assertTrue(all(provider['ok'] for provider in result['providers'].values()))
        self.assertIn('not guarantee', ' '.join(result['limitations']))
        calls = self.calls()
        self.assertEqual([(call['kind'], call['arguments']) for call in calls], [
            ('codex', ['--version']), ('codex', ['--help']),
            ('codex', ['exec', '--help']), ('codex', ['exec', 'resume', '--help']),
            ('claude', ['--version']), ('claude', ['--help'])])
        self.assertTrue(all(call['stdin'] == '' and call['cwd_files'] == [] for call in calls))
        self.assertEqual({path.name for path in self.root.iterdir()},
                         {'fake_codex', 'fake_claude', 'fixture.json', 'calls.jsonl'})

    def test_missing_and_nonexecutable_programs_are_actionable_and_do_not_hide_other_provider(self):
        missing = self.root / 'missing'
        result = self.command('--codex-command', str(missing), passed=False)
        provider = result['providers']['codex']
        self.assertIsNone(provider['executable'])
        self.assertEqual(provider['checks'][0]['code'], 'not_found')
        self.assertIn('--codex-command', provider['checks'][0]['message'])
        self.assertTrue(result['providers']['claude']['ok'])
        missing.write_text('Not executable')
        result = self.command('--codex-command', str(missing), passed=False)
        self.assertEqual(result['providers']['codex']['checks'][0]['code'], 'not_found')

    def test_missing_codex_flags_are_reported_in_their_actual_scope(self):
        self.config['codex_root'] = CODEX_ROOT.replace('  --sandbox <MODE>\n', '')
        self.config['codex_resume'] = CODEX_EXEC.replace('  --output-schema <FILE>\n', '')
        result = self.command(passed=False)
        checks = {check['name']: check for check in result['providers']['codex']['checks']}
        self.assertEqual(checks['help']['missing_flags'], ['--sandbox'])
        self.assertEqual(checks['resume_help']['missing_flags'], ['--output-schema'])
        self.assertTrue(checks['exec_help']['ok'])

    def test_prose_mentions_and_longer_flag_names_do_not_satisfy_required_flags(self):
        self.config['claude_root'] = CLAUDE_HELP.replace('  --json-schema <SCHEMA>',
            '  --json-schema-extra <SCHEMA>\nThis release does not support --json-schema.')
        result = self.command(passed=False)
        check = result['providers']['claude']['checks'][-1]
        self.assertEqual(check['missing_flags'], ['--json-schema'])

    def test_program_paths_with_spaces_and_path_lookup_remain_usable(self):
        program = self.root / 'fake codex'
        program.write_bytes((self.root / 'fake_codex').read_bytes())
        program.chmod(0o700)
        with patch.dict(os.environ, {'PATH': str(self.root)}):
            result = self.command('--codex-command', str(program), '--claude-command', 'fake_claude')
        self.assertEqual(result['providers']['codex']['executable'], str(program))

    def test_invalid_executable_arguments_and_unbounded_timeouts_fail_before_probes(self):
        for extra in (('--codex-command=',), ('--codex-command=--help',),
                      ('--codex-command', 'codex --help'), ('--probe-timeout', 'nan'),
                      ('--probe-timeout', 'inf'), ('--probe-timeout', '0'),
                      ('--probe-timeout', '11')):
            with self.subTest(extra=extra):
                stdout, stderr = io.StringIO(), io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = main(self.arguments(*extra))
                self.assertEqual(code, 2)
                self.assertEqual(stdout.getvalue(), '')
                self.assertEqual(json.loads(stderr.getvalue())['error']['code'], 'invalid_argument')
        self.assertEqual(self.calls(), [])

    def test_nonzero_probe_reports_failure_without_echoing_private_output_or_retrying(self):
        self.config['codex_case'] = 'nonzero'
        result = self.command(passed=False)
        check = result['providers']['codex']['checks'][-1]
        self.assertEqual(check['code'], 'probe_failed')
        self.assertEqual(check['exit_code'], 7)
        self.assertNotIn('SYNTHETIC_PRIVATE_DIAGNOSTIC', json.dumps(result))
        self.assertEqual(len([call for call in self.calls() if call['kind'] == 'codex']), 1)

    def test_split_unicode_stdout_remains_valid_when_stderr_arrives_between_chunks(self):
        self.config['codex_case'] = 'unicode'
        result = self.command()
        self.assertEqual(result['providers']['codex']['version'], 'codex synthetic – 1.2.3')
        self.assertNotIn('Benign local warning', result['providers']['codex']['version'])

    def test_timeout_stops_owned_descendants_and_keeps_independent_provider_available(self):
        self.config['codex_case'] = 'hang'
        began = time.monotonic()
        result = self.command('--probe-timeout', '0.5', passed=False)
        self.assertLess(time.monotonic() - began, 4)
        self.assertEqual(result['providers']['codex']['checks'][-1]['code'], 'probe_timeout')
        self.assertTrue(result['providers']['claude']['ok'])
        time.sleep(0.7)
        self.assertFalse((self.root / 'child-survived').exists())

    def test_completed_probe_stops_background_children_or_reports_cleanup_uncertainty(self):
        self.config['codex_case'] = 'background'
        result = self.command(passed=None)
        self.assertTrue(result['providers']['claude']['ok'])
        if not result['local_checks_passed']:
            # Darwin can return EPERM for an orphan zombie-only group after its
            # live child was stopped. Keep that uncertainty visible to callers.
            self.assertEqual(result['providers']['codex']['checks'][-1]['code'], 'probe_cleanup')
        time.sleep(0.7)
        self.assertFalse((self.root / 'child-survived').exists())

    def test_stdout_and_stderr_flood_is_bounded_without_deadlocking(self):
        self.config['codex_case'] = 'flood'
        began = time.monotonic()
        result = self.command('--probe-timeout', '1', passed=False)
        self.assertLess(time.monotonic() - began, 4)
        self.assertEqual(result['providers']['codex']['checks'][-1]['code'], 'probe_output_limit')
        self.assertLess(len(json.dumps(result)), 12000)

    def test_cleanup_timeout_is_a_failed_json_report_instead_of_a_traceback(self):
        from review_session.runner_process import terminate_group
        self.config['codex_case'] = 'background'
        cleanup_calls = []
        def cleanup_then_report_timeout(process):
            cleanup_calls.append(process.pid)
            if len(cleanup_calls) == 1:
                raise subprocess.TimeoutExpired('synthetic owned group cleanup', 2)
            terminate_group(process)
        with patch('review_session.doctor.terminate_group', side_effect=cleanup_then_report_timeout):
            result = self.command(passed=False)
        self.assertEqual(result['providers']['codex']['checks'][-1]['code'], 'probe_cleanup')
        self.assertEqual(cleanup_calls[0], cleanup_calls[1])

    def test_unsupported_runtime_reports_failure_without_launching_programs(self):
        with patch('review_session.doctor.sys.version_info', (3, 10, 0)):
            result = self.command(passed=False)
        self.assertFalse(result['runtime']['python']['ok'])
        self.assertEqual(self.calls(), [])
        with patch('review_session.doctor.os.name', 'nt'):
            result = self.command(passed=False)
        self.assertFalse(result['runtime']['platform']['ok'])
        self.assertEqual(self.calls(), [])

    def test_interrupt_returns_report_and_stops_only_owned_probe_children(self):
        self.config['codex_case'] = 'hang'
        self.write_fixture()
        process = subprocess.Popen([sys.executable, '-m', 'review_session', *self.arguments()],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: process.kill() if process.poll() is None else None)
        deadline = time.monotonic() + 4
        while not self.calls() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(self.calls())
        process.send_signal(signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=4)
        self.assertEqual(process.returncode, 2, stderr)
        self.assertEqual(stderr, '')
        result = json.loads(stdout)
        self.assertFalse(result['local_checks_passed'])
        self.assertEqual(result['providers']['codex']['checks'][-1]['code'], 'interrupted')
        self.assertEqual(len(self.calls()), 1)
        time.sleep(0.7)
        self.assertFalse((self.root / 'child-survived').exists())


if __name__ == '__main__':
    unittest.main()
