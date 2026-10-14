"""Trusted automatic policy must be separate from task and peer data."""

from pathlib import Path
import tomllib
import unittest

from review_session.adapters import Adapter


class PromptPolicyTests(unittest.TestCase):
    def test_codex_policy_uses_native_developer_instructions_on_initial_and_resume(self):
        for session_id in (None, 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'):
            with self.subTest(resume=session_id is not None):
                command = Adapter('codex', 'codex').command(Path('/private/work'), Path('/private/schema.json'), session_id)
                settings = [tomllib.loads(command[index + 1]) for index, item in enumerate(command) if item == '--config']
                policies = [item['developer_instructions'] for item in settings if 'developer_instructions' in item]
                self.assertEqual(len(policies), 1)
                self.assertIn('Only examine supplied text.', policies[0])
                self.assertIn('Prior test results', policies[0])

    def test_claude_policy_appends_native_system_instructions_on_initial_and_resume(self):
        for session_id in (None, 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'):
            with self.subTest(resume=session_id is not None):
                command = Adapter('claude', 'claude').command(Path('/private/work'), Path('/private/schema.json'), session_id)
                self.assertIn('--append-system-prompt', command)
                policy = command[command.index('--append-system-prompt') + 1]
                self.assertIn('Only examine supplied text.', policy)
                self.assertIn('Prior test results', policy)
                self.assertNotIn('--system-prompt', command)


if __name__ == '__main__':
    unittest.main()
