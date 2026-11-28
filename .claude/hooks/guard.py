"""Claude Code guard for this repo, run before every shell command (see .claude/settings.json).

- A commit that would publish this computer's home folder, the user's name, or a real-looking API
  key or GitHub token is stopped: everything committed here is public.
- A force push, which would rewrite the public history, is stopped.
- Publishing a release, which reaches every installed copy, needs the owner's yes.
- Merging a pull request, or pushing to `main`, needs the owner's yes however it is spelled: a
  person approves every change that reaches `main`. Skipping the required checks (--admin) or turning
  on auto-merge (--auto) is stopped.

Every check runs on every command and the strictest answer wins (stop, then ask, then run).

Reads the hook payload on stdin and answers with a PreToolUse decision on stdout; says nothing when
the command is fine. Standard library only, so it runs on Windows and macOS alike.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

KEY = re.compile(r"sk-ant-api\d\d-[A-Za-z0-9_-]{20,}|\bgh[pousr]_[A-Za-z0-9]{30,}|\bgithub_pat_[A-Za-z0-9_]{30,}")
FORCE_PUSH = re.compile(r"\bgit\b[^;&|\n]*\bpush\b[^;&|\n]*(\s--force(-with-lease)?\b|\s-[a-zA-Z]*f\b|\s\+[^\s]+)")
RELEASE = re.compile(r"\bdepop_seller\s+release\b(?![^;&|\n]*--dry-run)|\bgh\s+release\s+(create|delete|upload|edit)\b")
COMMIT = re.compile(r"\bgit\b[^;&|\n]*\bcommit\b")
# any way of running gh: gh, gh.exe, a quoted full path ("C:/Program Files/GitHub CLI/gh.exe")
GH = r"\bgh(?:\.exe)?[\"']?"
FLAGS = r"(?:-\S+(?:\s+[^-\s]\S*)?\s+)*"          # flags, some with a value: -R owner/repo, --repo x
# `gh pr merge`, with flags such as -R before or between the words - but not `merge` in a title
MERGE = re.compile(GH + r"\s+" + FLAGS + r"pr\s+" + FLAGS + r"merge\b")
# any GitHub API call that writes: a method other than GET, a field, a body, or GraphQL
API_WRITE = re.compile(GH + r"\s+api\b[^;&|\n]*(?:\s(?:-X|--method)[\s=]*(?!GET\b)[A-Za-z]"
                       r"|\s(?:-f|-F|--field|--raw-field|--input)\b|\sgraphql\b)", re.IGNORECASE)
BYPASS = re.compile(r"\s--(?:admin|auto)\b")
PUSH = re.compile(r"\bgit\b(?![^;&|\n]*\bstash\b)[^;&|\n]*\bpush\b(?P<rest>[^;&|\n]*)")
CONTINUATION = re.compile(r"(?:\\|`)\r?\n")       # a bash backslash or PowerShell backtick continuation
MAX_FILE = 2 * 1024 * 1024


def _short_name(folder: Path) -> str | None:
    """Windows' 8.3 spelling of a folder (C:\\Users\\ABCDEF~1), which keeps part of the name."""
    if os.name != "nt":
        return None
    import ctypes
    buffer = ctypes.create_unicode_buffer(1024)
    if ctypes.windll.kernel32.GetShortPathNameW(str(folder), buffer, len(buffer)):
        return buffer.value
    return None


def markers(home: Path) -> list[str]:
    """What must never appear in a commit, lower-cased: the home folder in every spelling, and its
    name (on most computers the user's own name)."""
    found = {str(home), home.as_posix()}
    short = _short_name(home)
    if short:
        found |= {short, Path(short).as_posix()}
    if len(home.name) >= 5:
        found.add(home.name)
    return sorted({m.lower() for m in found if m})


def without_repo_path(command: str, repo: Path) -> str:
    """The command minus the repo's own folder, which a command may name (`cd <repo> && git commit`)
    without anything of it being committed. Any other mention of the home folder still counts."""
    spellings = {str(repo), repo.as_posix()}
    short = _short_name(repo)
    if short:
        spellings |= {short, Path(short).as_posix()}
    posix = repo.as_posix()
    if len(posix) > 2 and posix[1] == ":":                       # Git Bash spells C:/x as /c/x
        spellings.add("/" + posix[0].lower() + posix[2:])
    for spelling in sorted(spellings, key=len, reverse=True):
        command = re.sub(re.escape(spelling), "<repo>", command, flags=re.IGNORECASE)
    return command


def leaks(text: str, marks: list[str]) -> list[str]:
    """Plain names of what this text gives away (never the secret itself)."""
    found = []
    lower = text.lower()
    if any(m in lower for m in marks):
        found.append("this computer's home folder or the user's name")
    if KEY.search(text):
        found.append("a real-looking API key or GitHub token")
    return found


def _git(cwd: str, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", check=False)
    return done.stdout if done.returncode == 0 else ""


def pending_changes(cwd: str) -> dict[str, str]:
    """Every line a commit could take from here: added lines of tracked files (staged or not, since
    `git add` may run in the same command) and the contents of new, not-ignored files."""
    out: dict[str, str] = {}
    current = None
    for line in _git(cwd, "diff", "HEAD", "--no-color", "-U0").splitlines():
        if line.startswith("+++ "):
            current = line[6:] if line.startswith("+++ b/") else None
        elif current and line.startswith("+"):
            out[current] = out.get(current, "") + line[1:] + "\n"
    for name in _git(cwd, "ls-files", "--others", "--exclude-standard").splitlines():
        path = Path(cwd) / name
        try:
            if path.is_file() and path.stat().st_size <= MAX_FILE:
                out[name] = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
    return out


def pushes_main(rest: str, cwd: str) -> str | None:
    """'deny', 'ask' or None for what follows `git push`. Only a push that clearly names another
    branch goes ahead; anything that might reach `main`, or that cannot be read for sure, asks."""
    words = re.sub(r"[\"'()]", " ", rest).split()
    flags = [w for w in words if w.startswith("-")]
    if "--mirror" in flags:                         # mirrors every branch, forced and with deletions
        return "deny"
    if "--all" in flags:
        return "ask"
    refspecs = [w for w in words if not w.startswith("-")][1:]   # the first word is the remote
    on_main = None
    for spec in refspecs or [""]:
        target = spec.split(":")[-1].lstrip("+").removeprefix("refs/heads/")
        if target in ("", "HEAD", "@"):             # nothing named: the current branch
            if on_main is None:
                on_main = _git(cwd, "rev-parse", "--abbrev-ref", "HEAD").strip() in ("main", "")
            if on_main:
                return "ask"
        elif target == "main":
            return "ask"
    return None


def check_merge(command: str, cwd: str) -> tuple[str, str] | None:
    """A person approves every change that reaches `main`: any merge, any GitHub API call that writes,
    and any push that might reach `main` ask; skipping the checks is stopped."""
    merging = MERGE.search(command) or API_WRITE.search(command)
    if merging and BYPASS.search(command):
        return "deny", ("Never skip the required checks (--admin) or turn on auto-merge (--auto). Wait for the "
                        "checks, then merge normally.")
    if merging:
        return "ask", "This can put a change on main through GitHub, and the owner approves every change to main."
    for push in PUSH.finditer(command):
        verdict = pushes_main(push.group("rest"), cwd)
        if verdict == "deny":
            return "deny", "A mirror push overwrites and deletes branches on GitHub. Push one branch instead."
        if verdict == "ask":
            return "ask", "This push may reach main, and the owner approves every change to main."
    return None


def check_commit(command: str, cwd: str, home: Path) -> tuple[str, str] | None:
    """Nothing personal in a commit: everything committed here is public."""
    if not COMMIT.search(command):
        return None
    marks = markers(home)
    problems = [f"the command: {what}" for what in leaks(without_repo_path(command, Path(cwd)), marks)]
    for name, text in pending_changes(cwd).items():
        problems += [f"{name}: {what}" for what in leaks(text, marks)]
    if problems:
        return "deny", ("Everything committed here is public, and this commit would include "
                        + "; ".join(sorted(set(problems))[:5]) + ". Remove it, then commit again.")
    return None


def decide(command: str, cwd: str, home: Path) -> tuple[str, str] | None:
    """(decision, reason) for a shell command, or None to let it run. Every check runs and the
    strictest answer wins, so one part of a command cannot switch off the check on another."""
    command = CONTINUATION.sub(" ", command)
    verdicts = [
        ("deny", "Force pushing rewrites the public history of this repo. Push normally, or ask the owner.")
        if FORCE_PUSH.search(command) else None,
        ("ask", "This publishes a release that every installed copy will be offered. The owner decides.")
        if RELEASE.search(command) else None,
        check_merge(command, cwd),
        check_commit(command, cwd, home),
    ]
    for level in ("deny", "ask"):
        found = [v for v in verdicts if v and v[0] == level]
        if found:
            return level, " ".join(reason for _, reason in found)
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return 0
    command = str((payload.get("tool_input") or {}).get("command") or "")
    if not command:
        return 0
    cwd = next((c for c in (payload.get("cwd"), os.environ.get("CLAUDE_PROJECT_DIR"), os.getcwd())
                if c and Path(c).is_dir()), os.getcwd())
    try:
        verdict = decide(command, cwd, Path.home())
    except Exception as e:  # noqa: BLE001 - a guard that cannot check asks instead of crashing
        verdict = ("ask", f"The repo's guard could not check this command ({type(e).__name__}). Please look at it.")
    if verdict:
        decision, reason = verdict
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                                 "permissionDecision": decision,
                                                 "permissionDecisionReason": reason}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
