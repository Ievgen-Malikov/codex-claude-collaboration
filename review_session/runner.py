"""Opt-in coordinator for finite, text-only Codex and Claude review turns."""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import uuid

from .adapters import Adapter, RESPONSE_SCHEMA
from .core import PARTICIPANTS, Session, SessionError, atomic_json, initialize, timestamp, utc_now
from .runner_process import Cancellation, Invocation, cancellation_signals, execute
from .runner_store import MAX_TEXT_BYTES, configuration, load, owner_lock, prepare_job_directory, save, sha256, summary, validate_response


ARTIFACT = 'artifacts/result.md'


class OperatorStopped(Exception):
    """The authoritative helper state has already been closed."""


def artifact_hash(session: Session) -> str | None:
    path = session.root / ARTIFACT
    if not path.exists() and not path.is_symlink():
        return None
    return session._artifact(ARTIFACT)['sha256']


def artifact_text(session: Session) -> str:
    directory = os.open(session.root / 'artifacts', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        descriptor = os.open('result.md', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(descriptor, 'rb') as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                raise SessionError('invalid_artifact', 'Report must be a regular UTF-8 file.')
            content = handle.read(MAX_TEXT_BYTES + 1)
        if len(content) > MAX_TEXT_BYTES:
            raise SessionError('invalid_artifact', 'Report exceeds 131072 UTF-8 bytes.')
        return content.decode('utf-8')
    except UnicodeError:
        raise SessionError('invalid_artifact', 'Report must contain valid UTF-8 text.') from None
    finally:
        os.close(directory)


def publish_artifact(session: Session, text: str, expected: str | None) -> None:
    """Compare and publish under the helper lock; preserve independent edits."""
    with session.locked() as state:
        session._active(state)
        current = artifact_hash(session)
        produced = sha256(text)
        if current == produced:
            return  # A completed local publication was interrupted before journaling.
        if current != expected:
            raise SessionError('artifact_changed', 'Result was edited independently; the runner preserved it.')
        directory = os.open(session.root / 'artifacts', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        temporary = '.result-' + uuid.uuid4().hex
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                 0o600, dir_fd=directory)
            with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            if artifact_hash(session) != expected:
                raise SessionError('artifact_changed', 'Result changed during publication; the independent edit was preserved.')
            session._active(state)
            os.replace(temporary, 'result.md', src_dir_fd=directory, dst_dir_fd=directory)
            os.fsync(directory)
        finally:
            try:
                os.unlink(temporary, dir_fd=directory)
            except FileNotFoundError:
                pass
            os.close(directory)


class Coordinator:
    def __init__(self, session: Session, data: dict, workdir: Path, cancellation: Cancellation):
        self.session = session
        self.data = data
        self.workdir = workdir
        self.cancellation = cancellation
        self.adapters = {agent: Adapter(**config) for agent, config in data['config']['adapters'].items()}

    def save(self):
        save(self.session.root, self.data)

    def check_open(self):
        if self.cancellation.requested:
            raise SessionError('runner_cancelled', 'Coordinator interrupted; partial work was preserved.')
        with self.session.locked() as state:
            if state['phase'] == 'STOPPED':
                raise OperatorStopped
            self.session._active(state)

    def validate_response(self, job: dict, response: dict) -> None:
        if job['stage'] == 'review' and response.get('reviewed_sha256') != job['artifact_sha256']:
            raise SessionError('artifact_changed', 'Review verdict does not name the supplied artifact version.')
        try:
            validate_response(job, response)
        except (ValueError, UnicodeError) as error:
            raise SessionError('runner_response', str(error)) from None

    def request(self, agent: str, stage: str, round_number: int) -> tuple[dict, dict]:
        self.check_open()
        # First passes are independent even if a manual message appeared while
        # the other participant was preparing. They never see the transcript.
        messages = [] if stage == 'proposal' else self.session.inbox(agent, 0)['messages']
        observed = artifact_hash(self.session)
        artifact = ''
        if observed is not None:
            artifact = artifact_text(self.session)
            if sha256(artifact) != observed:
                raise SessionError('artifact_changed', 'Artifact changed while preparing a turn.')
        if stage == 'review' and observed is None:
            raise SessionError('invalid_artifact', 'No report exists to review.')
        request = {'goal': self.session.status()['goal'],
                   'inputs': self.data['inputs'], 'agent': agent, 'stage': stage,
                   'round': round_number, 'messages': messages,
                   'artifact': artifact if stage != 'proposal' else '',
                   'artifact_sha256': observed if stage != 'proposal' else None}
        job = {'agent': agent, 'stage': stage, 'round': round_number, 'status': 'running',
               'message_ids': [item['id'] for item in messages], 'artifact_sha256': observed,
               'peer_message_ids': [item['id'] for item in messages if item['agent'] != agent],
               'started_at': timestamp(utc_now()), 'pid': None, 'response': None, 'provider_session_id': None}
        return request, job

    def invoke(self, specifications: list[tuple[str, str, str, int]]) -> list[dict]:
        invocations = []
        for identifier, agent, stage, round_number in specifications:
            if identifier in self.data['jobs']:
                continue
            request, job = self.request(agent, stage, round_number)
            # No job has been journaled and no invocation can have started yet.
            # Recover interrupted prompt/schema preparation without replacing logs.
            directory = prepare_job_directory(self.session.root, identifier)
            atomic_json(directory / 'prompt.json', request)
            schema = directory / 'schema.json'
            atomic_json(schema, RESPONSE_SCHEMA)
            self.data['jobs'][identifier] = job
            # A crash from this point onward is an unknown invocation; recording
            # before Popen closes the dangerous launch-before-journal window.
            self.save()
            working = self.workdir / agent
            working.mkdir(exist_ok=True)
            command = self.adapters[agent].command(working, schema, self.data['provider_sessions'].get(agent))
            invocations.append(Invocation(identifier, command, working, directory / 'prompt.json',
                                          directory / 'stdout.jsonl', directory / 'stderr.log'))
            print(f'[runner] {stage}: {agent} (round {round_number})', file=sys.stderr, flush=True)

        def started(identifier, pid):
            self.data['jobs'][identifier]['pid'] = pid
            self.save()

        def completed(identifier, stdout):
            job = self.data['jobs'][identifier]
            provider_id, response = self.adapters[job['agent']].decode(stdout)
            previous = self.data['provider_sessions'].get(job['agent'])
            if previous is not None and previous != provider_id:
                raise SessionError('runner_response', 'Provider resumed a different conversation; result was discarded.')
            self.validate_response(job, response)
            self.data['provider_sessions'][job['agent']] = provider_id
            job.update(status='completed', response=response, provider_session_id=provider_id)
            self.save()

        execute(invocations, self.data['config']['turn_timeout'], self.check_open, started, completed)
        return [self.data['jobs'][item[0]] for item in specifications]

    def apply(self, identifier: str) -> dict:
        job = self.data['jobs'][identifier]
        if job['status'] == 'applied':
            self.validate_response(job, job['response'])
            return job['response']
        self.check_open()
        response = job['response']
        self.validate_response(job, response)
        if job['stage'] == 'draft':
            publish_artifact(self.session, response['artifact'], job['artifact_sha256'])
        elif job['stage'] == 'review':
            if artifact_hash(self.session) != job['artifact_sha256']:
                raise SessionError('artifact_changed', 'A late review cannot approve a changed report.')
            if response['verdict'] == 'approve':
                self.session.approve(job['agent'], ARTIFACT, job['artifact_sha256'],
                                     expected_peer_ids=job['peer_message_ids'])
        kind = 'proposal' if job['stage'] == 'proposal' else 'finding' if response['verdict'] in ('comment', 'disagree') and job['stage'] == 'review' else 'reply'
        self.check_open()
        self.session.send(job['agent'], kind, response['message'],
                          operation_id=self.data['session_id'] + ':' + identifier)
        job['status'] = 'applied'
        self.save()
        return response

    def finish(self, reason: str, outcome: str | None = None) -> dict:
        output = self.session.stop(reason, outcome)
        self.data['status'] = 'complete'
        self.save()
        output['runner'] = summary(self.session.root)
        return output

    def drive(self) -> dict:
        with self.session.locked() as state:
            preparing = state['phase'] == 'PREPARING'
        if preparing:
            for agent in PARTICIPANTS:
                self.session.join(agent)
            self.session.start()
        self.invoke([('proposal-agent-a', 'agent-a', 'proposal', 0),
                     ('proposal-agent-b', 'agent-b', 'proposal', 0)])
        # Publish only after both independent invocations completed.
        for agent in PARTICIPANTS:
            self.apply('proposal-' + agent)
        last_verdict = 'comment'
        for round_number in range(1, self.data['config']['max_rounds'] + 1):
            draft = f'draft-{round_number}'
            self.invoke([(draft, 'agent-a', 'draft', round_number)])
            self.apply(draft)
            review = f'review-{round_number}-agent-b'
            last_review_id = review
            self.invoke([(review, 'agent-b', 'review', round_number)])
            last_verdict = self.apply(review)['verdict']
            if last_verdict == 'approve':
                own = f'review-{round_number}-agent-a'
                last_review_id = own
                self.invoke([(own, 'agent-a', 'review', round_number)])
                last_verdict = self.apply(own)['verdict']
                if last_verdict == 'approve':
                    return self.finish('Both agents reviewed and approved the exact report version.')
        # The final objection arrived after the editor's last draft. Retain it
        # in the delivered report as an explicitly attributed closure record.
        last_review = self.data['jobs'][last_review_id]
        closing = (f"\n\n## Coordinator closure record\n\nReview round limit reached. "
                   f"Latest verdict: {last_review['response']['verdict']} by {last_review['agent']}.\n\n"
                   + last_review['response']['message'] + '\n')
        final_draft = self.data['jobs'][draft]['response']['artifact']
        publish_artifact(self.session, final_draft + closing, sha256(final_draft))
        return self.finish('Review round limit reached; see report and transcript for reservations.',
                           'DISAGREED' if last_verdict == 'disagree' else None)


def run(path: str, *, resume: bool = False, goal: str | None = None, inputs: list[str] | None = None,
        minutes: float | None = None, max_rounds: int | None = None, turn_timeout: float | None = None,
        codex_command: str | None = None, claude_command: str | None = None,
        codex_model: str | None = None, claude_model: str | None = None) -> dict:
    options = (goal, inputs, minutes, max_rounds, turn_timeout, codex_command, claude_command, codex_model, claude_model)
    if resume:
        if any(value is not None for value in options):
            raise SessionError('invalid_argument', '--resume uses the frozen task and configuration; omit other options.')
    else:
        if goal is None:
            raise SessionError('invalid_argument', 'A new automated review requires --goal.')
        config, snapshots = configuration(inputs or [], 3 if max_rounds is None else max_rounds,
                                          180 if turn_timeout is None else turn_timeout,
                                          'codex' if codex_command is None else codex_command,
                                          'claude' if claude_command is None else claude_command,
                                          codex_model, claude_model)
        initialized = initialize(path, goal, 30 if minutes is None else minutes)
    session = Session(path)
    with owner_lock(session.root):
        state = session.status()
        if resume:
            data = load(session.root, state['session_id'])
            if state['phase'] == 'STOPPED':
                state['runner'] = summary(session.root)
                return state
            if any(job['status'] == 'running' for job in data['jobs'].values()):
                data.update(status='unknown', error='Interrupted invocation has an unknown outcome.')
                save(session.root, data)
                raise SessionError('runner_outcome_unknown', 'An interrupted agent invocation may still be running. Inspect private logs/processes, stop this session, and start a fresh review; no model call was retried.')
            if data['status'] != 'running':
                raise SessionError('invalid_runner', 'This runner cannot be resumed; inspect its recorded error.')
        else:
            data = {'schema_version': 1, 'session_id': initialized['session_id'], 'config': config,
                    'inputs': snapshots, 'jobs': {}, 'provider_sessions': {}, 'status': 'running', 'error': None}
            save(session.root, data)
        # No project config, instructions or input files exist in agent CWDs.
        with tempfile.TemporaryDirectory(prefix='agent-review-work-') as temporary, cancellation_signals() as cancellation:
            coordinator = Coordinator(session, data, Path(temporary), cancellation)
            try:
                return coordinator.drive()
            except OperatorStopped:
                # execute() has cleaned up owned groups before reaching this handler.
                # Retain recorded PIDs as historical evidence, not signal targets.
                for job in data['jobs'].values():
                    if job['status'] == 'running':
                        job.update(status='failed', error='Coordination stopped; owned processes were terminated.')
                data['status'] = 'complete'
                save(session.root, data)
                output = session.status()
                output['runner'] = summary(session.root)
                return output
            except (KeyboardInterrupt, SessionError, OSError) as error:
                if isinstance(error, KeyboardInterrupt):
                    error = SessionError('runner_cancelled', 'Coordinator interrupted; partial work was preserved.')
                data.update(status='failed', error=str(error))
                for job in data['jobs'].values():
                    if job['status'] == 'running':
                        job['status'] = 'failed'
                save(session.root, data)
                session.stop('Automatic review stopped: ' + str(error))
                raise error
