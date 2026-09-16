# Frozen task execution

Read `spec/README.md`, the assigned task in `spec/tasks.json`, and `spec/06-harness.md`.
The Spec is the only implementation baseline. Work only on the exact assigned
modify/create paths. Do not change Spec, architecture, dependencies, interfaces,
other tasks, or accepted checkers. Report `SPEC_CHANGE_REQUIRED` with evidence
when the contract is incomplete. Assigned execution agents must not spawn agents
or proceed to the next task. The trusted coordinator may dispatch each new task
in a fresh context after independently accepting its dependencies.

Enforcement is **diff-gate-only**: a file allowlist and a subsequent Git diff
check, not operating-system write isolation. Docker/VM and external execution
platforms are not prerequisites.

The coordinator starts a fresh context per task from a clean accepted baseline,
passes frozen Spec, task ID, exact allowlist, accepted dependencies and commands,
and keeps `.git/ir-harness/freeze.json` outside the candidate diff. Never copy
predecessor conversation history into the next task. T00 is a bootstrap: the
coordinator independently reviews both checker implementations and adversarial
tests before recording SHA-256 for both checkers. Later tasks require those hashes.

Run assigned task tests, then:

```text
python tools/check_spec_contract.py --spec-root spec
python tools/check_task_scope.py --task Txx --base <task-base-sha> --spec-root spec --evidence .git/ir-harness/freeze.json
git diff --check <task-base-sha>
```

Write only the assigned `.harness/runs/Txx/result.json`, recording changed files,
command argv, exit codes, SHA-256 of captured logs, acceptance IDs and limitations.
A passing report is not coordinator acceptance. The coordinator independently
checks changes and tests, rejects failed candidates and never dispatches a later
task until acceptance. Stop the execution context after the report; retain audit
records without claiming to destroy OS processes, credentials or chat history.

CI always validates static Spec references and runs guard tests. Task scope is
checked only when a coordinator explicitly supplies all task/base/freeze inputs
through the optional workflow inputs. Ordinary branch CI has no current task and
must not compare all historical changes against an arbitrary task allowlist.
The freeze input must come from the coordinator's trusted record, never from the
candidate's report. CI does not establish trust in candidate-controlled checkers;
independent coordinator review and accepted checker hashes remain mandatory.
