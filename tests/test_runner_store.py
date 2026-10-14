"""Input and report integrity boundaries for the automatic coordinator."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from review_session.core import Session, SessionError, initialize
from review_session.cli import main
from review_session.runner import artifact_text, publish_artifact
from review_session.runner_store import MAX_TEXT_BYTES, configuration, read_input, sha256


class RunnerFileTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def session(self):
        path = self.root / 'session'
        initialize(str(path), 'Synthetic report integrity check', 30)
        session = Session(str(path))
        session.join('agent-a')
        session.join('agent-b')
        session.start()
        return session

    def test_input_snapshot_preserves_utf8_and_exact_line_endings(self):
        path = self.root / 'source.txt'
        path.write_bytes('Пример\r\nEvidence\n'.encode('utf-8'))
        snapshot = read_input(str(path))
        self.assertEqual(snapshot['text'], 'Пример\r\nEvidence\n')
        self.assertEqual(snapshot['sha256'], sha256(snapshot['text']))

    def test_inputs_reject_symlinks_special_files_and_oversize(self):
        regular = self.root / 'text.txt'
        regular.write_text('Evidence')
        symlink = self.root / 'link.txt'
        symlink.symlink_to(regular)
        fifo = self.root / 'pipe'
        os.mkfifo(fifo)
        huge = self.root / 'large.txt'
        huge.write_bytes(b'x' * (MAX_TEXT_BYTES + 1))
        for path in (symlink, fifo, self.root, huge):
            with self.subTest(path=path):
                with self.assertRaises(SessionError) as error:
                    read_input(str(path))
                self.assertEqual(error.exception.code, 'invalid_argument')

    def test_total_input_budget_and_missing_executable_rejected(self):
        paths = [self.root / name for name in ('one.txt', 'two.txt')]
        for path in paths:
            path.write_bytes(b'x' * (MAX_TEXT_BYTES // 2 + 1))
        with self.assertRaises(SessionError) as error:
            configuration([str(path) for path in paths], 3, 180, 'python3', 'python3', None, None)
        self.assertEqual(error.exception.code, 'invalid_argument')
        with self.assertRaises(SessionError) as error:
            configuration([str(paths[0])], 3, 180, 'NO-SUCH-REVIEW-CLI', 'python3', None, None)
        self.assertEqual(error.exception.code, 'runner_unavailable')

    def test_explicit_empty_executable_does_not_fall_back_to_real_models(self):
        from contextlib import redirect_stderr
        import io
        source = self.root / 'input.txt'
        source.write_text('Synthetic evidence')
        target = self.root / 'never-created'
        for option in ('--codex-command', '--claude-command'):
            with self.subTest(option=option), redirect_stderr(io.StringIO()):
                with patch('review_session.runner.execute', side_effect=AssertionError('Model call must not start')):
                    code = main(['run', str(target), '--goal', 'Review', '--input', str(source), option, ''])
                self.assertEqual(code, 2)
                self.assertFalse(target.exists())

    def test_report_publication_is_idempotent_and_preserves_changed_report(self):
        session = self.session()
        publish_artifact(session, 'First report\r\n', None)
        self.assertEqual(artifact_text(session), 'First report\r\n')
        publish_artifact(session, 'First report\r\n', None)
        path = session.root / 'artifacts/result.md'
        path.write_text('Independent revision')
        with self.assertRaises(SessionError) as error:
            publish_artifact(session, 'New report', sha256('First report\r\n'))
        self.assertEqual(error.exception.code, 'artifact_changed')
        self.assertEqual(path.read_text(), 'Independent revision')

    def test_report_edit_during_write_is_rechecked_before_publication(self):
        session = self.session()
        publish_artifact(session, 'Original', None)
        path = session.root / 'artifacts/result.md'
        original_fsync = os.fsync
        calls = []
        def fsync_then_edit(descriptor):
            original_fsync(descriptor)
            if not calls:
                path.write_text('Independent edit during publication')
            calls.append(descriptor)
        with patch('review_session.runner.os.fsync', side_effect=fsync_then_edit):
            with self.assertRaises(SessionError) as error:
                publish_artifact(session, 'Runner revision', sha256('Original'))
        self.assertEqual(error.exception.code, 'artifact_changed')
        self.assertEqual(path.read_text(), 'Independent edit during publication')
        self.assertEqual(list((session.root / 'artifacts').glob('.result-*')), [])

    def test_report_reader_rejects_invalid_utf8(self):
        session = self.session()
        path = session.root / 'artifacts/result.md'
        path.write_bytes(b'\xff')
        with self.assertRaises(SessionError) as error:
            artifact_text(session)
        self.assertEqual(error.exception.code, 'invalid_artifact')


if __name__ == '__main__':
    unittest.main()
