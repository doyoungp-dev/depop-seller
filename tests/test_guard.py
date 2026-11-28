"""The Claude Code guard in .claude/hooks/guard.py: what it stops, what it asks about, and that an
ordinary command passes untouched. It runs before every shell command Claude starts in this repo."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from depop_seller import config

GUARD = config.PROJECT_ROOT / ".claude" / "hooks" / "guard.py"
_spec = importlib.util.spec_from_file_location("guard", GUARD)
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)

FAKE_KEY = "sk-ant-api" + "03-" + "x" * 30          # built here so no key-shaped text sits in the repo


@pytest.mark.parametrize("command", ["git push --force origin main", "git push -f", "git push origin +main",
                                     "git push --force-with-lease", "cd x && git push -uf origin main"])
def test_a_force_push_is_stopped(command, tmp_path: Path):
    assert guard.decide(command, str(tmp_path), tmp_path)[0] == "deny"


@pytest.mark.parametrize("command", [".venv/bin/python -m depop_seller release 1.2.0",
                                     "python -m depop_seller release", "gh release create v1.2.0 dist/x.zip"])
def test_publishing_a_release_asks_the_owner(command, tmp_path: Path):
    assert guard.decide(command, str(tmp_path), tmp_path)[0] == "ask"


@pytest.mark.parametrize("command", ["git status", "git push origin my-change", "git push -u origin my-change",
                                     "python -m depop_seller release --dry-run", "gh release list",
                                     "gh pr create --title x", "gh pr view 7", "python -m pytest -q"])
def test_ordinary_commands_pass(command, tmp_path: Path):
    assert guard.decide(command, str(tmp_path), tmp_path) is None


def test_personal_paths_names_and_keys_are_recognised_in_any_spelling(tmp_path: Path):
    home = tmp_path / "Users" / "Some Body"
    marks = guard.markers(home)
    for text in (f"built in {home}", f"built in {home.as_posix().upper()}", "thanks, some body!"):
        assert guard.leaks(text, marks) == ["this computer's home folder or the user's name"]
    assert guard.leaks(f"key = {FAKE_KEY}", marks) == ["a real-looking API key or GitHub token"]
    assert guard.leaks("sk-ant-test-short and C:/Users/you/DepopSeller", marks) == []


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    for args in (["init", "-q"], ["config", "user.email", "t@example.com"], ["config", "user.name", "t"]):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)
    (repo / "ok.txt").write_text("hello", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "start"], cwd=repo, check=True, capture_output=True)
    return repo


def test_a_commit_carrying_the_home_folder_or_a_key_is_stopped(tmp_path: Path):
    repo, home = _repo(tmp_path), tmp_path / "Users" / "Some Body"
    assert guard.decide("git commit -m tidy", str(repo), home) is None
    (repo / "notes.md").write_text(f"photos are in {home}/DepopSeller", encoding="utf-8")   # new, not yet added
    decision, reason = guard.decide("git add -A && git commit -m notes", str(repo), home)
    assert decision == "deny" and "notes.md" in reason and str(home) not in reason
    (repo / "notes.md").unlink()
    (repo / "ok.txt").write_text(f"hello {FAKE_KEY}", encoding="utf-8")                      # tracked, changed
    decision, reason = guard.decide("git commit -am change", str(repo), home)
    assert decision == "deny" and "ok.txt" in reason and FAKE_KEY not in reason


def test_naming_the_repo_s_own_folder_in_the_command_is_fine_but_nothing_else_personal(tmp_path: Path):
    home = tmp_path / "Users" / "Some Body"
    repo = home / "Desktop" / "project"
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True, capture_output=True)
    for spelling in (str(repo), repo.as_posix()):
        assert guard.decide(f'cd "{spelling}" && git commit -m tidy', str(repo), home) is None
    decision, _ = guard.decide(f'git commit -m "photos live in {home}/Pictures"', str(repo), home)
    assert decision == "deny"


@pytest.mark.parametrize("command", [
    "gh pr merge 7 --squash --delete-branch",
    '"C:/Program Files/GitHub CLI/gh.exe" pr merge 7 --squash',                 # a full path, quoted
    "gh.exe pr merge 7",
    "gh pr -R doyoungp-dev/depop-seller merge 7",                                # flags before the subcommand
    "gh pr merge 3 --squash && gh pr merge 9 --squash",                          # more than one
    "gh api -X PUT repos/doyoungp-dev/depop-seller/pulls/7/merge",               # the REST API
    "gh api repos/o/r/merges -f base=main -f head=feat",                         # any API call that writes
    "gh api --method=PATCH repos/o/r/git/refs/heads/main",
    "gh api graphql -F query=@mutation.graphql",
    "gh api graphql -f query='mutation { mergePullRequest(input: {}) { clientMutationId } }'",
    "git push origin main", "git push origin HEAD:main", "git push origin refs/heads/main",
    'git push origin "main"', "git push origin 'feat:main'", 'bash -c "git push origin main"',
    "powershell -Command \"git push origin main\"", "git push --all origin",
])
def test_every_merge_and_every_push_to_main_waits_for_the_owner(command, tmp_path: Path):
    decision, reason = guard.decide(command, str(tmp_path), tmp_path)
    assert decision == "ask" and "owner" in reason


def test_a_bare_push_from_main_waits_for_the_owner_but_one_from_a_branch_does_not(tmp_path: Path):
    repo = _repo(tmp_path)
    subprocess.run(["git", "branch", "-M", "main"], cwd=repo, check=True, capture_output=True)
    for command in ("git push", "git push origin", "git push origin HEAD", "git push -u origin @"):
        assert guard.decide(command, str(repo), tmp_path)[0] == "ask", command
    subprocess.run(["git", "switch", "-q", "-c", "my-change"], cwd=repo, check=True, capture_output=True)
    for command in ("git push", "git push origin HEAD", "git push -u origin my-change", "git stash push"):
        assert guard.decide(command, str(repo), tmp_path) is None, command
    assert guard.decide("git push --mirror origin", str(repo), tmp_path)[0] == "deny"


@pytest.mark.parametrize("command", ["gh pr create --title 'Every merge waits for the owner'", "gh pr list --search merge",
                                     "gh pr view 7", "gh api repos/doyoungp-dev/depop-seller/pulls/7",
                                     "gh api -X GET repos/o/r/actions/runs"])
def test_reading_and_creating_pull_requests_is_not_mistaken_for_a_merge(command, tmp_path: Path):
    assert guard.decide(command, str(tmp_path), tmp_path) is None


def test_merging_can_never_skip_the_checks_or_go_unattended(tmp_path: Path):
    bash_newline, ps_newline = chr(92) + chr(10), "`" + chr(10)                 # line continuations
    for command in ("gh pr merge 7 --admin --squash", "gh pr merge 7 --squash --auto", "gh pr merge 7 --admin=true",
                    "gh pr merge 7 --squash " + bash_newline + "  --admin", "gh pr merge 7 " + ps_newline + " --auto"):
        assert guard.decide(command, str(tmp_path), tmp_path)[0] == "deny", command


def test_one_part_of_a_command_cannot_switch_off_another_check(tmp_path: Path):
    repo, home = _repo(tmp_path), tmp_path / "Users" / "Some Body"
    decision, reason = guard.decide(f'git commit -m "see {home}" && gh pr merge 7 --squash', str(repo), home)
    assert decision == "deny" and "public" in reason                            # the commit check still ran


def test_the_hook_answers_claude_code_in_its_own_format(tmp_path: Path):
    payload = json.dumps({"tool_name": "Bash", "cwd": str(tmp_path), "tool_input": {"command": "git push -f"}})
    done = subprocess.run([sys.executable, str(GUARD)], input=payload, capture_output=True, text=True, check=True)
    answer = json.loads(done.stdout)["hookSpecificOutput"]
    assert answer["hookEventName"] == "PreToolUse" and answer["permissionDecision"] == "deny"
    quiet = json.dumps({"tool_name": "Bash", "cwd": str(tmp_path), "tool_input": {"command": "git status"}})
    assert subprocess.run([sys.executable, str(GUARD)], input=quiet, capture_output=True, text=True).stdout == ""


def test_the_shared_settings_run_the_guard_and_keep_the_key_file_unreadable():
    settings = json.loads((config.PROJECT_ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
    hooks = settings["hooks"]["PreToolUse"]
    assert any("Bash" in h["matcher"] and any("guard.py" in x["command"] for x in h["hooks"]) for h in hooks)
    assert {"Read(./.env)", "Edit(./.env)", "Read(~/DepopSeller/.env)"} <= set(settings["permissions"]["deny"])
    assert settings["attribution"] == {"commit": "", "pr": "", "sessionUrl": False}
