"""Synthetic end-to-end runner tests: real subprocesses, no model providers."""

from contextlib import redirect_stderr, redirect_stdout
import hashlib
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
from review_session.core import Session


FAKE_CLI = r'''
import json, pathlib, subprocess, sys, time
request = json.load(sys.stdin)
case = json.loads(request['inputs'][0]['text'])
role = request['agent']
stage = request['stage']
root = pathlib.Path(__file__).parent
with (root / 'calls.jsonl').open('a') as handle:
    handle.write(json.dumps({'agent': role, 'stage': stage, 'round': request['round'],
                            'messages': request['messages'], 'inputs': request['inputs'],
                            'artifact': request['artifact'], 'artifact_sha256': request['artifact_sha256'],
                            'argv': sys.argv[1:]}) + '\n')
if case.get('hang') and stage == 'review' and role == 'agent-b':
    subprocess.Popen([sys.executable, '-c',
        "import pathlib,time; time.sleep(2); pathlib.Path(" + repr(str(root / 'child-survived')) + ").touch()"])
    time.sleep(30)
if case.get('background_child') and stage == 'draft':
    child = subprocess.Popen([sys.executable, '-c',
        "import pathlib,time; time.sleep(1); pathlib.Path(" + repr(str(root / 'background-survived')) + ").touch()"])
    (root / 'background.pid').write_text(str(child.pid))
if case.get('slow'):
    time.sleep(case['slow'])
if case.get('fail') == role:
    print('provider failed', file=sys.stderr)
    sys.exit(1)
if case.get('malformed'):
    print('not JSON')
    sys.exit(0)
verdict = 'comment'
artifact = ''
reviewed = ''
if stage == 'draft':
    artifact = '# Synthetic report\n\nEvidence and unresolved concerns.\n'
    if case.get('crlf_artifact'):
        artifact = artifact.replace('\n', '\r\n')
elif stage == 'review':
    verdict = 'approve'
    if role == 'agent-b' and case.get('revision') and request['round'] == 1:
        verdict = 'comment'
    if case.get('disagree'):
        verdict = 'disagree'
    if case.get('partial'):
        verdict = 'comment'
    reviewed = request['artifact_sha256']
    if case.get('wrong_hash'):
        reviewed = '0' * 64
response = {'message': role + ' synthetic ' + stage, 'artifact': artifact,
            'verdict': verdict, 'reviewed_sha256': reviewed}
sid = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa' if role == 'agent-a' else 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
if 'codex' in pathlib.Path(__file__).name:
    print(json.dumps({'type':'thread.started','thread_id':sid}))
    print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':json.dumps(response)}}))
    print(json.dumps({'type':'turn.completed','usage':{}}))
else:
    print(json.dumps({'type':'result','subtype':'success','is_error':False,
                      'session_id':sid,'structured_output':response}))
'''


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.session_path = self.root / 'session'
        self.input = self.root / 'task.txt'
        self.input.write_text('{}')
        for name in ('fake_codex', 'fake_claude'):
            path = self.root / name
            path.write_text('#!' + sys.executable + '\n' + FAKE_CLI)
            path.chmod(0o700)

    def arguments(self, *extra):
        return ['run', str(self.session_path), '--goal', 'Review synthetic local text',
                '--input', str(self.input), '--codex-command', str(self.root / 'fake_codex'),
                '--claude-command', str(self.root / 'fake_claude'), '--turn-timeout', '3', *extra]

    def command(self, args, error=None):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(args)
        if error:
            self.assertEqual(code, 2, (stdout.getvalue(), stderr.getvalue()))
            # Progress goes to stderr before the one final JSON error.
            value = json.loads(stderr.getvalue().splitlines()[-1])
            self.assertEqual(value['error']['code'], error)
            return value
        self.assertEqual(code, 0, stderr.getvalue())
        return json.loads(stdout.getvalue())

    def calls(self):
        return [json.loads(line) for line in (self.root / 'calls.jsonl').read_text().splitlines()]

    def test_full_review_is_independent_and_approves_exact_report(self):
        result = self.command(self.arguments())
        self.assertEqual(result['outcome'], 'AGREED')
        self.assertTrue(result['agreement_current'])
        calls = self.calls()
        self.assertEqual(len(calls), 5)
        first = [item for item in calls if item['stage'] == 'proposal']
        self.assertEqual({item['agent'] for item in first}, {'agent-a', 'agent-b'})
        self.assertTrue(all(item['messages'] == [] for item in first))
        transcript = Session(str(self.session_path)).inbox('agent-a', 0)['messages']
        self.assertEqual([item['kind'] for item in transcript[:2]], ['proposal', 'proposal'])
        self.assertEqual(len({item['operation_id'] for item in transcript}), len(transcript))
        self.assertIn('Synthetic report', (self.session_path / 'artifacts/result.md').read_text())
        self.assertEqual(result['runner']['status'], 'complete')

    def test_revisions_use_explicit_provider_ids_and_bounded_rounds(self):
        self.input.write_text('{"revision":true}')
        result = self.command(self.arguments('--max-rounds', '2'))
        self.assertEqual(result['outcome'], 'AGREED')
        calls = self.calls()
        self.assertEqual(len(calls), 7)
        for item in calls:
            if item['stage'] != 'proposal':
                self.assertNotIn('--last', item['argv'])
                self.assertNotIn('--continue', item['argv'])
                self.assertIn('resume' if item['agent'] == 'agent-a' else '--resume', item['argv'])

    def test_report_with_crlf_line_endings_is_reviewed_as_exact_original_bytes(self):
        self.input.write_text('{"crlf_artifact":true}')
        result = self.command(self.arguments())
        self.assertEqual(result['outcome'], 'AGREED')
        self.assertTrue(result['agreement_current'])
        report = (self.session_path / 'artifacts/result.md').read_bytes()
        self.assertEqual(report, b'# Synthetic report\r\n\r\nEvidence and unresolved concerns.\r\n')
        digest = hashlib.sha256(report).hexdigest()
        reviews = [item for item in self.calls() if item['stage'] == 'review']
        self.assertEqual(len(reviews), 2)
        self.assertTrue(all(item['artifact'].encode('utf-8') == report for item in reviews))
        self.assertTrue(all(item['artifact_sha256'] == digest for item in reviews))

    def test_round_limit_preserves_disagreement_and_partial_result(self):
        for case, outcome in (({'disagree': True}, 'DISAGREED'), ({'partial': True}, 'PARTIAL')):
            with self.subTest(outcome=outcome):
                self.session_path = self.root / outcome
                self.input.write_text(json.dumps(case))
                result = self.command(self.arguments('--max-rounds', '1'))
                self.assertEqual(result['outcome'], outcome)
                self.assertTrue((self.session_path / 'artifacts/result.md').exists())
                report = (self.session_path / 'artifacts/result.md').read_text()
                self.assertIn('Coordinator closure record', report)
                self.assertIn('agent-b synthetic review', report)

    def test_provider_failure_closes_partial_and_preserves_evidence(self):
        self.input.write_text('{"fail":"agent-b"}')
        self.command(self.arguments(), error='runner_provider')
        self.assertEqual(Session(str(self.session_path)).status()['outcome'], 'PARTIAL')
        self.assertTrue(list((self.session_path / '.runner').glob('*/stderr.log')))

    def test_malformed_response_and_wrong_hash_never_approve(self):
        for case, error in (({'malformed': True}, 'runner_response'), ({'wrong_hash': True}, 'artifact_changed')):
            with self.subTest(case=case):
                self.session_path = self.root / error
                self.input.write_text(json.dumps(case))
                self.command(self.arguments(), error=error)
                status = Session(str(self.session_path)).status()
                self.assertEqual(status['outcome'], 'PARTIAL')
                self.assertFalse(status['approvals'])

    def test_timeout_terminates_owned_child_group_and_retains_draft(self):
        self.input.write_text('{"hang":true}')
        args = self.arguments()
        args[args.index('--turn-timeout') + 1] = '1'
        self.command(args, error='runner_timeout')
        self.assertTrue((self.session_path / 'artifacts/result.md').exists())
        time.sleep(2.1)
        self.assertFalse((self.root / 'child-survived').exists())

    def test_successful_turn_does_not_leave_background_descendants_running(self):
        self.input.write_text('{"background_child":true}')
        result = self.command(self.arguments())
        self.assertEqual(result['outcome'], 'AGREED')
        self.assertTrue((self.root / 'background.pid').exists())
        draft_pid = self.journal()['jobs']['draft-1']['pid']
        self.addCleanup(self.terminate_synthetic_group, draft_pid)
        time.sleep(1.1)
        self.assertFalse((self.root / 'background-survived').exists())

    def test_deadline_includes_initial_turns_and_rejects_late_results(self):
        self.input.write_text('{"slow":.3}'.replace(':.', ':0.'))
        self.command(self.arguments('--minutes', '.001'), error='expired')
        status = Session(str(self.session_path)).status()
        self.assertEqual(status['outcome'], 'PARTIAL')
        self.assertEqual(Session(str(self.session_path)).inbox('agent-a', 0)['messages'], [])

    def test_validation_happens_before_creating_session_or_launching_models(self):
        self.command(self.arguments('--max-rounds', '0'), error='invalid_argument')
        self.assertFalse(self.session_path.exists())
        self.input.write_bytes(b'\xff')
        self.command(self.arguments(), error='invalid_argument')
        self.assertFalse(self.session_path.exists())
        self.assertFalse((self.root / 'calls.jsonl').exists())

    def test_closed_resume_is_read_only_and_does_not_call_models(self):
        self.command(self.arguments())
        before = {str(path.relative_to(self.session_path)): path.read_bytes()
                  for path in self.session_path.rglob('*') if path.is_file()}
        calls = self.calls()
        resumed = self.command(['run', str(self.session_path), '--resume'])
        self.assertEqual(resumed['outcome'], 'AGREED')
        self.assertEqual(calls, self.calls())
        after = {str(path.relative_to(self.session_path)): path.read_bytes()
                 for path in self.session_path.rglob('*') if path.is_file()}
        self.assertEqual(before, after)

    def test_resume_cannot_override_frozen_configuration(self):
        self.command(['run', str(self.session_path), '--resume', '--goal', 'Different goal'], error='invalid_argument')

    def test_process_stop_closes_session_and_suppresses_new_turns(self):
        self.input.write_text('{"slow":2}')
        process = subprocess.Popen([sys.executable, '-m', 'review_session', *self.arguments()],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: process.kill() if process.poll() is None else None)
        self.wait_for(lambda: (self.root / 'calls.jsonl').exists())
        Session(str(self.session_path)).stop('Operator stopped')
        stdout, stderr = process.communicate(timeout=5)
        self.assertEqual(process.returncode, 0, stderr)
        self.assertEqual(json.loads(stdout)['stop_reason'], 'Operator stopped')
        count = len(self.calls())
        time.sleep(.1)
        self.assertEqual(count, len(self.calls()))

    def test_sigterm_preserves_partial_and_exits_json(self):
        self.input.write_text('{"slow":2}')
        process = subprocess.Popen([sys.executable, '-m', 'review_session', *self.arguments()],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: process.kill() if process.poll() is None else None)
        self.wait_for(lambda: (self.root / 'calls.jsonl').exists())
        process.send_signal(signal.SIGTERM)
        _, stderr = process.communicate(timeout=5)
        self.assertEqual(process.returncode, 2, stderr)
        self.assertEqual(json.loads(stderr.splitlines()[-1])['error']['code'], 'runner_cancelled')
        self.assertEqual(Session(str(self.session_path)).status()['outcome'], 'PARTIAL')

    def test_second_coordinator_cannot_own_or_stop_active_runner(self):
        self.input.write_text('{"slow":2}')
        process = subprocess.Popen([sys.executable, '-m', 'review_session', *self.arguments()],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: process.kill() if process.poll() is None else None)
        self.wait_for(lambda: (self.root / 'calls.jsonl').exists() and len(self.calls()) == 2)
        before = self.calls()
        self.command(['run', str(self.session_path), '--resume'], error='runner_busy')
        self.assertEqual(self.calls(), before)
        self.assertEqual(Session(str(self.session_path)).status()['phase'], 'ACTIVE')
        self.assertEqual(self.journal()['status'], 'running')
        Session(str(self.session_path)).stop('Synthetic owner conflict cleanup')
        stdout, stderr = process.communicate(timeout=5)
        self.assertEqual(process.returncode, 0, stderr)
        self.assertEqual(json.loads(stdout)['stop_reason'], 'Synthetic owner conflict cleanup')

    def test_unexpected_coordinator_death_is_unknown_and_never_retries_or_signals_saved_pids(self):
        self.input.write_text('{"slow":2}')
        process = subprocess.Popen([sys.executable, '-m', 'review_session', *self.arguments()],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: process.kill() if process.poll() is None else None)
        self.wait_for(lambda: (self.root / 'calls.jsonl').exists() and len(self.calls()) == 2)
        self.wait_for(lambda: all(job['pid'] is not None for job in self.journal()['jobs'].values()))
        child_pids = [job['pid'] for job in self.journal()['jobs'].values()]
        for pid in child_pids:
            self.addCleanup(self.terminate_synthetic_group, pid)
        process.kill()
        process.communicate(timeout=5)
        calls = self.calls()
        self.command(['run', str(self.session_path), '--resume'], error='runner_outcome_unknown')
        self.assertEqual(self.calls(), calls)
        self.assertEqual(self.journal()['status'], 'unknown')
        self.assertTrue(all(job['status'] == 'running' for job in self.journal()['jobs'].values()))
        self.assertEqual(Session(str(self.session_path)).status()['phase'], 'ACTIVE')
        for pid in child_pids:
            os.kill(pid, 0)  # A stale PID is evidence, never a runner cancellation target.
        Session(str(self.session_path)).stop('Synthetic unknown outcome cleanup')

    def checkpoint_after_first_durable_message(self):
        original = Session.send

        def interrupted_send(session, *args, **kwargs):
            original(session, *args, **kwargs)
            # Abrupt loss after the local effect, before the applied journal write.
            raise SystemExit('Synthetic hard crash after message publication')

        with patch.object(Session, 'send', interrupted_send), self.assertRaises(SystemExit):
            self.command(self.arguments())
        self.assertEqual(Session(str(self.session_path)).status()['phase'], 'ACTIVE')
        self.assertTrue(all(job['status'] == 'completed' for job in self.journal()['jobs'].values()))

    def test_completed_job_replays_local_effect_without_repeated_model_call_or_message(self):
        self.checkpoint_after_first_durable_message()
        before = self.calls()
        transcript = Session(str(self.session_path)).inbox('agent-a', 0)['messages']
        self.assertEqual(len(transcript), 1)
        result = self.command(['run', str(self.session_path), '--resume'])
        self.assertEqual(result['outcome'], 'AGREED')
        calls = self.calls()
        self.assertEqual(calls[:2], before)
        self.assertEqual(sum(item['stage'] == 'proposal' for item in calls), 2)
        self.assertEqual(len(calls), 5)
        transcript = Session(str(self.session_path)).inbox('agent-a', 0)['messages']
        self.assertEqual(len(transcript), 5)
        self.assertEqual(len({item['operation_id'] for item in transcript}), 5)
        self.assertEqual(sum(item['agent'] == 'agent-a' and item['kind'] == 'proposal' for item in transcript), 1)

    def test_resumed_prompts_use_frozen_text_after_source_is_edited_or_removed(self):
        for remove_source in (False, True):
            with self.subTest(remove_source=remove_source):
                self.session_path = self.root / ('removed-source' if remove_source else 'edited-source')
                self.input.write_text('{}')
                previous_calls = len(self.calls()) if (self.root / 'calls.jsonl').exists() else 0
                self.checkpoint_after_first_durable_message()
                snapshot = self.journal()['inputs']
                if remove_source:
                    self.input.unlink()
                else:
                    self.input.write_text('{"fail":"agent-a","new_private_text":"not part of review"}')
                result = self.command(['run', str(self.session_path), '--resume'])
                self.assertEqual(result['outcome'], 'AGREED')
                calls = self.calls()[previous_calls:]
                self.assertEqual(len(calls), 5)
                self.assertTrue(all(item['inputs'] == snapshot for item in calls))
                self.assertTrue(all(item['inputs'][0]['text'] == '{}' for item in calls))

    def test_corrupt_journal_is_rejected_before_any_new_model_invocation(self):
        corruptions = (
            ('wrong-session', lambda data: data.update(session_id='99999999-9999-4999-8999-999999999999')),
            ('altered-snapshot', lambda data: data['inputs'][0].update(text='changed')),
            ('wrong-stage', lambda data: data['jobs']['proposal-agent-a'].update(stage='draft')),
            ('invalid-applied-response', lambda data: data['jobs']['proposal-agent-a'].update(status='applied', response={})),
        )
        for name, corrupt in corruptions:
            with self.subTest(corruption=name):
                self.session_path = self.root / name
                self.checkpoint_after_first_durable_message()
                journal = self.journal()
                corrupt(journal)
                (self.session_path / 'runner.json').write_text(json.dumps(journal))
                before = self.calls()
                self.command(['run', str(self.session_path), '--resume'], error='invalid_runner')
                self.assertEqual(self.calls(), before)
                self.assertEqual(Session(str(self.session_path)).status()['phase'], 'ACTIVE')

    def journal(self):
        return json.loads((self.session_path / 'runner.json').read_text())

    @staticmethod
    def terminate_synthetic_group(pid):
        try:
            os.killpg(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass

    def wait_for(self, predicate):
        deadline = time.monotonic() + 5
        while not predicate():
            if time.monotonic() > deadline:
                self.fail('Subprocess did not reach expected state')
            time.sleep(.02)


if __name__ == '__main__':
    unittest.main()
