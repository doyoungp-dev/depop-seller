"""Claude Code guard for this repo, run before every shell command (see .claude/settings.json).

- A commit that would publish this computer's home folder, the user's name, or a real-looking API
  key or GitHub token is stopped: everything committed here is public.
- A force push, which would rewrite the public history, is stopped.
- Publishing a release, which reaches every installed copy, needs the owner's yes.
- Merging a pull request goes ahead by itself only when it changes nothing but docs, stylesheets and
  tests (and removes no test check); anything else needs the owner's yes. Skipping the required
  checks (--admin) or turning on auto-merge (--auto) is stopped.

Reads the hook payload on stdin and answers with a PreToolUse decision on stdout; says nothing when
the command is fine. Standard library only, so it runs on Windows and macOS alike.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

KEY = re.compile(r"sk-ant-api\d\d-[A-Za-z0-9_-]{20,}|\bgh[pousr]_[A-Za-z0-9]{30,}|\bgithub_pat_[A-Za-z0-9_]{30,}")
FORCE_PUSH = re.compile(r"\bgit\b[^;&|\n]*\bpush\b[^;&|\n]*(\s--force(-with-lease)?\b|\s-[a-zA-Z]*f\b|\s\+[^\s]+)")
RELEASE = re.compile(r"\bdepop_seller\s+release\b(?![^;&|\n]*--dry-run)|\bgh\s+release\s+(create|delete|upload|edit)\b")
COMMIT = re.compile(r"\bgit\b[^;&|\n]*\bcommit\b")
MERGE = re.compile(r"\bgh\s+pr\s+merge\b")
MERGE_NUMBER = re.compile(r"\bgh\s+pr\s+merge\s+(?:-\S+\s+)*#?(\d+)\b")
MERGE_BYPASS = re.compile(r"\bgh\s+pr\s+merge\b[^;&|\n]*\s--(admin|auto)\b")
REMOVED_CHECK = re.compile(r"^-(?!--)\s*(assert\b|def test_|with pytest\.raises|pytest\.raises)")
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


def low_risk(path: str) -> bool:
    """A file Claude may merge a change to without the owner: docs, stylesheets and tests. Anything
    else - the app's code, its rules and settings, any CLAUDE.md - waits for the owner."""
    if Path(path).name == "CLAUDE.md":
        return False
    return (path.startswith("docs/") or path in ("README.md", "CHANGELOG.md", "SECURITY.md")
            or path.startswith("tests/") or (path.startswith("depop_seller/static/") and path.endswith(".css")))


def _gh(cwd: str, *args: str) -> str | None:
    """`gh`'s output, or None when it is missing or fails (then the owner is asked instead)."""
    exe = shutil.which("gh") or next((p for p in (r"C:\Program Files\GitHub CLI\gh.exe", "/opt/homebrew/bin/gh",
                                                  "/usr/local/bin/gh") if Path(p).is_file()), None)
    if exe is None:
        return None
    done = subprocess.run([exe, *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", check=False)
    return done.stdout if done.returncode == 0 else None


def review_merge(command: str, cwd: str) -> tuple[str, str] | None:
    """A merge goes ahead by itself only for a pull request that changes nothing but docs, stylesheets
    and tests, and removes no test check; the owner says yes to anything else."""
    if MERGE_BYPASS.search(command):
        return "deny", ("Never skip the required checks (--admin) or turn on auto-merge (--auto). Wait for the "
                        "checks, then merge normally.")
    number = MERGE_NUMBER.search(command)
    if not number:
        return "ask", "Merging a pull request without its number: the owner decides which one."
    names = _gh(cwd, "pr", "diff", number.group(1), "--name-only")
    patch = _gh(cwd, "pr", "diff", number.group(1))
    if names is None or patch is None:
        return "ask", f"The guard could not read pull request {number.group(1)}'s changes, so the owner decides."
    owners = [name for name in names.split() if not low_risk(name)]
    removed_checks = [line for line in patch.splitlines() if REMOVED_CHECK.match(line)]
    if owners or removed_checks:
        why = []
        if owners:
            why.append("it changes " + ", ".join(owners[:4]) + (" and more" if len(owners) > 4 else ""))
        if removed_checks:
            why.append("it removes or changes a test check")
        return "ask", f"Pull request {number.group(1)} waits for the owner: " + "; ".join(why) + "."
    return None


def decide(command: str, cwd: str, home: Path) -> tuple[str, str] | None:
    """(decision, reason) for a shell command, or None to let it run."""
    if FORCE_PUSH.search(command):
        return "deny", "Force pushing rewrites the public history of this repo. Push normally, or ask the owner."
    if RELEASE.search(command):
        return "ask", "This publishes a release that every installed copy will be offered. The owner decides."
    if MERGE.search(command):
        return review_merge(command, cwd)
    if COMMIT.search(command):
        marks = markers(home)
        problems = [f"the command: {what}" for what in leaks(without_repo_path(command, Path(cwd)), marks)]
        for name, text in pending_changes(cwd).items():
            problems += [f"{name}: {what}" for what in leaks(text, marks)]
        if problems:
            return "deny", ("Everything committed here is public, and this commit would include "
                            + "; ".join(sorted(set(problems))[:5]) + ". Remove it, then commit again.")
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
