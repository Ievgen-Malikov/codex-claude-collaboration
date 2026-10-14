"""Owned subprocess cleanup uses synthetic local children, never providers."""

from contextlib import redirect_stderr, redirect_stdout
import errno
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from review_session.cli import main
from review_session.core import Session, SessionError
from review_session.runner import Coordinator
from review_session.runner_process import Invocation, execute, terminate_group


class RunnerProcessTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.processes = []

    def launch(self, *arguments, **options):
        process = self.popen(*arguments, **options)
        self.processes.append(process)
        self.addCleanup(self.cleanup_child, process)
        return process

    @staticmethod
    def cleanup_child(process):
        if process.poll() is None:
            terminate_group(process)

    def invocation(self, identifier, code):
        directory = self.root / identifier
        directory.mkdir()
        prompt = directory / 'prompt.json'
        prompt.write_text('{}')
        return Invocation(identifier, [sys.executable, '-c', code], directory,
                          prompt, directory / 'stdout.jsonl', directory / 'stderr.log')

    def test_failed_decode_does_not_terminate_completed_group_twice(self):
        invocations = [self.invocation('completed', "print('invalid response')"),
                       self.invocation('peer', 'import time; time.sleep(30)')]
        primary = SessionError('runner_response', 'Synthetic malformed response')
        terminated = []

        def cleanup(process):
            terminated.append(process.pid)
            terminate_group(process)

        def completed(identifier, output):
            raise primary

        self.popen = subprocess.Popen
        with patch('review_session.runner_process.subprocess.Popen', side_effect=self.launch), \
                patch('review_session.runner_process.terminate_group', side_effect=cleanup), \
                self.assertRaises(SessionError) as caught:
            execute(invocations, 3, lambda: None, lambda identifier, pid: None, completed)
        self.assertIs(caught.exception, primary)
        self.assertEqual(terminated, [process.pid for process in self.processes])
        self.assertTrue(all(process.poll() is not None for process in self.processes))

    def test_cleanup_error_preserves_primary_evidence_and_attempts_every_peer(self):
        invocations = [self.invocation('completed', "print('invalid response')"),
                       self.invocation('blocked-peer', 'import time; time.sleep(30)'),
                       self.invocation('other-peer', 'import time; time.sleep(30)')]
        primary = SessionError('runner_response', 'Synthetic malformed response')
        attempted = []

        def cleanup(process):
            attempted.append(process.pid)
            if process is self.processes[1]:
                raise PermissionError(errno.EPERM, 'Synthetic denied group termination')
            terminate_group(process)

        def completed(identifier, output):
            raise primary

        diagnostics = io.StringIO()
        self.popen = subprocess.Popen
        with redirect_stderr(diagnostics), \
                patch('review_session.runner_process.subprocess.Popen', side_effect=self.launch), \
                patch('review_session.runner_process.terminate_group', side_effect=cleanup), \
                self.assertRaises(SessionError) as caught:
            execute(invocations, 3, lambda: None, lambda identifier, pid: None, completed)
        self.assertEqual(caught.exception.code, 'runner_cleanup')
        self.assertIs(caught.exception.__cause__, primary)
        self.assertIn('runner_response', str(caught.exception))
        self.assertIn('Synthetic malformed response', str(caught.exception))
        self.assertIn('Synthetic denied group termination', str(caught.exception))
        self.assertIn(str(self.processes[1].pid), str(caught.exception))
        self.assertIn('cleanup', diagnostics.getvalue())
        self.assertEqual(attempted, [process.pid for process in self.processes])
        self.assertIsNotNone(self.processes[2].poll())

    def test_operator_stop_reports_incomplete_cleanup_as_failure(self):
        executable = self.root / 'synthetic_cli'
        executable.write_text('#!' + sys.executable + '\nimport time; time.sleep(30)\n')
        executable.chmod(0o700)
        source = self.root / 'input.txt'
        source.write_text('Synthetic stop and cleanup evidence')
        session_path = self.root / 'session'
        stopped = False
        original_save = Coordinator.save

        def save_then_stop(coordinator):
            nonlocal stopped
            original_save(coordinator)
            jobs = coordinator.data['jobs']
            if not stopped and len(jobs) == 2 and all(job['pid'] is not None for job in jobs.values()):
                stopped = True
                coordinator.session.stop('Synthetic operator stop')

        def cleanup(process):
            if process is self.processes[0]:
                raise PermissionError(errno.EPERM, 'Synthetic denied group termination')
            terminate_group(process)

        stdout, stderr = io.StringIO(), io.StringIO()
        self.popen = subprocess.Popen
        with redirect_stdout(stdout), redirect_stderr(stderr), \
                patch('review_session.runner_process.subprocess.Popen', side_effect=self.launch), \
                patch('review_session.runner_process.terminate_group', side_effect=cleanup), \
                patch.object(Coordinator, 'save', new=save_then_stop):
            code = main(['run', str(session_path), '--goal', 'Review synthetic text',
                         '--input', str(source), '--codex-command', str(executable),
                         '--claude-command', str(executable)])
        self.assertEqual(code, 2, stderr.getvalue())
        self.assertEqual(stdout.getvalue(), '')
        errors = []
        for line in stderr.getvalue().split('\n'):
            try:
                value = json.loads(line)
            except ValueError:
                continue
            if isinstance(value, dict) and value.get('ok') is False and 'error' in value:
                errors.append(value)
        self.assertEqual(len(errors), 1, stderr.getvalue())
        error = errors[0]
        self.assertEqual(error['error']['code'], 'runner_cleanup')
        self.assertIn('Synthetic denied group termination', error['error']['message'])
        self.assertIn('cleanup', stderr.getvalue())
        journal = json.loads((session_path / 'runner.json').read_text())
        self.assertEqual(journal['status'], 'failed')
        self.assertIn('cleanup', journal['error'])
        self.assertTrue(all(job['status'] == 'failed' for job in journal['jobs'].values()))
        self.assertEqual(Session(str(session_path)).status()['stop_reason'], 'Synthetic operator stop')
        self.assertIsNotNone(self.processes[1].poll())


if __name__ == '__main__':
    unittest.main()
