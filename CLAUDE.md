# depop_seller

Depop Seller turns a shoot's clothing photos into Depop listings, on the seller's own computer:
Claude groups the photos into items, the seller fixes the grouping by drag and drop, Claude Code
writes each description in the seller's style, and a Chrome helper fills in Depop's listing form
for the seller to check and post. Windows and macOS. The people using it are not engineers, and the code
is public.

This file is the short core: the rules that apply to every task. The detail lives here:

- [`docs/architecture.md`](docs/architecture.md) - how each feature works and why. **Read a
  feature's section before changing it, and update it in the same commit.**
- [`docs/LESSONS.md`](docs/LESSONS.md) - failures and the rule or test each one left behind. Add an
  entry when a failure teaches a rule.
- [`docs/decisions/`](docs/decisions/) - the big choices: the Chrome helper, subscription versus API,
  everything local, White Background switched off.
- `chrome_extension/CLAUDE.md` and `depop_seller/static/CLAUDE.md` - rules for the helper and for the
  pages, loaded when you work in those folders.
- `.claude/skills/` - `release`, `mac-check` and `verify-ui`; `.claude/agents/privacy-reviewer.md`
  checks a change for anything personal before it is committed.

## Reporting back to the owner

- **Every time a task is finished, end with a summary and a TL;DR** (owner's request, 2026-11-01): first a short summary of what changed and what was checked, then a **TL;DR** of two or three plain-language lines - what it means for the owner and what (if anything) they need to do next. Plain words, no jargon; say what is still open.


## How changes are made

- **Work on a branch, then a pull request.** `git switch -c <short-name>`, commit there, push the
  branch and open a pull request with `gh pr create`. CI (tests, Ruff and mypy on Windows and macOS)
  must pass; the owner reviews the diff and merges it with a squash merge. Never merge a pull request
  or turn on auto-merge yourself unless the owner says so for that pull request. Small direct pushes
  to `main` only when the owner asks for them.
- **An independent review before the owner merges.** After opening a pull request, run
  `/code-review` on it: it reviews the diff in a fresh subagent that never saw the conversation
  (Claude Code's best practices; it runs on the owner's subscription, with no GitHub app or secret).
  Report only problems that affect correctness, not style. Fix every confirmed finding on the
  branch, then give the owner a short summary of what was found and fixed before they merge.
- **`main` is protected on GitHub:** no force pushes, no deletion, and a pull request cannot be merged
  until the Windows and macOS checks pass. The owner is an admin and can still push to `main`
  directly, which `release` does for its `Release X.Y.Z` commit and tag.
- **Before every commit:** `ruff check .`, `mypy` and `pytest -q`. For anything that will be read in
  public (docs, release notes, the README), have the `privacy-reviewer` agent check the diff.
- **After a change to a page or a route,** check it in the real app on a demo data folder
  (`verify-ui` skill), never on the seller's data.
- **Commit subjects are written for sellers:** they become the release notes and the app's
  "What's new".

## Invariants

Each is explained, with its tests, in `docs/architecture.md` (section named in brackets).

- The reviewer's photo order (`photo_no`) is sacred: nothing re-sorts it. (Photo pipeline)
- The app only ever adds to `raw_image/`; its own work never changes, moves or deletes a photo.
  Deleting a batch is the seller's explicit choice and goes to the Recycle Bin or Trash. (Pages)
- The API key is for grouping only. Descriptions and style changes run on the seller's Claude
  subscription, enforced twice in code. (Descriptions; decision 0002)
- The app never presses Post. The Depop tab never calls the app; the helper's background worker does.
  (Selling on Depop; decision 0001)
- Only Depop's pages get CORS, and only on the helper's routes; every foreign POST is refused. (Safety)
- No console windows; closing the app window closes the app. (Safety)
- Updates touch the app folder only. `DepopSeller.zip` keeps its `depop_seller_app/` folder, the
  installer's `AppId` never changes, and changing `project.dependencies` sends every installed copy
  to a new installer - a release decision, never a tidy-up. (Releases)
- Nothing that is built or installed may name a folder of the release machine. (Releases)
- Windows and Mac are equals. (Environment, below)

## Ownership and commit rules

- Project of GitHub user `doyoungp-dev`, **public** at `github.com/doyoungp-dev/depop-seller` (branch `main`, MIT licence) - named `depop_seller` until 2026-11-01, when it was renamed to the usual hyphenated form; GitHub forwards the old address, so **never create a new repo called `depop_seller`** (that would end the forwarding). The Python package and the local folders keep `depop_seller` (Python names cannot have hyphens). Copies installed before 1.1.6 look for updates under the old name and were reinstalled by hand (owner's call). The history from before publication lives in the private `depop_seller-archive` and never goes public.
- **Everything committed is public - code, docs, tests and commit messages alike.** Nothing personal is ever committed: no photos, no `manifest.csv` (the grouping), no `depop_seller.db`, no `.env`, not the seller's own `description_style.md`, no local paths (a Windows home folder contains a real name), no shop handle, no real listings, no family or friends. All of that lives in the data folder outside the repo (see Data layout). Commit messages describe the software, never whose shop or which batch prompted a change.
- **A personal project, not work.** The GitHub account is also used for the owner's job and belongs to an organization there: never list, clone, read or call any organization's repositories or APIs, and never suggest company resources (org Actions, org repos, a work email) for this project. The login on the owner's machines can also reach the organization (the owner's choice); this project still only ever touches `doyoungp-dev/depop-seller` and `doyoungp-dev/depop_seller-archive`. CI notification emails follow the account's notification settings, not this repo.
- Commits are made with the repo-local git identity that is already configured (the owner's); do not change it.
- Never commit images. `raw_image/`, `sort_image/`, `thumbs/` and the whole `product_image/` tree are gitignored. In `.claude/` only `settings.json`, `hooks/`, `skills/` and `agents/` are committed (everything else there stays on each computer, and none of it ships in the app): the settings deny reading or editing any `.env`, turn commit attribution off, and run `.claude/hooks/guard.py` before every shell command - it stops a commit that would publish this computer's home folder, the user's name or a real-looking key, stops force pushes, and asks before a release is published (`tests/test_guard.py`). If the guard stops something, fix the cause; never work around it.
- Never commit secrets. `ANTHROPIC_API_KEY` is read from the environment, falling back to `.env` in the data folder (and, for old installs, the app folder). Never read, print, or edit a `.env`; never ask the user to paste a key into chat. Test fixtures use keys that are obviously fake (`sk-ant-test-...`), never the real `sk-ant-api03-` shape, which secret scanners flag.
- **No cloud infrastructure.** Everything runs on the user's own computer (local files, local SQLite). The only network calls are the Anthropic API for photo grouping, Claude Code on the user's subscription for descriptions, and Depop's website in the user's own Chrome, plus (only while the switched-off White Background feature is on) one download of its cut-out model from GitHub, made only after the user confirms it in the Review page. Do not propose or add hosted services, containers or deployment tooling. GitHub Releases are how the app is distributed and updated; that is the one exception, and the app only talks to GitHub when the user presses **Check for updates** or **Update** in Settings - never in the background. **CI (since 2026-11-01, owner's call):** `.github/workflows/tests.yml` runs the whole test suite with pytest on GitHub's `windows-latest` and `macos-latest` runners (Python 3.14, `pip install -e .[dev]`) on every push to `main`, every pull request, and by hand from the Actions tab - free on this public repo. It only tests: it builds and publishes nothing, needs no secrets (never give it the API key), and `release` still runs the tests locally and publishes by hand. A red X on a commit means a test failed on that system - read the log on the Actions tab before releasing. It cannot click dialogs, Gatekeeper or Depop, so the MacBook still checks those by hand. `.github` is in `share.SKIP_DIRS`: it is not part of the app.
- **Releases** are one command on the Windows machine: `python -m depop_seller release [X.Y.Z] [--notes ...] [--dry-run]` - use the `release` skill. It refuses a dirty tree or a branch other than `main`, and refuses unless this checkout is a fast-forward of `origin/main` with the same root commit - **that guard is what keeps the private pre-publication history from ever reaching the public repo, even through a tag**. It runs the tests, writes the version everywhere it lives (including the README's two download buttons and `CHANGELOG.md`), builds `DepopSeller.zip`, `DepopSeller-Mac.zip` and the Windows installer, tags, pushes and publishes all three files. Default notes are the commit subjects since the last release. Pushing to `main` reaches no user by itself. Details: docs/architecture.md (Releases).

## Environment

- **Cross-platform since 2026-09-23: Windows, macOS and Linux.** Anything OS-specific goes in `desktop.py` (open a folder, open an app window) or behind a `sys.platform` / `os.name` branch with a test that fakes the other platform - never a bare `os.startfile` or `taskkill` in feature code. The owner develops on Windows and on a MacBook (a second clone of this repo - `git pull` before starting, push when done); the whole test suite runs on both (the stub Claude CLI in the tests is a `.cmd` on Windows and an executable shell script elsewhere), and paths for an OS you are not on are covered by tests that monkeypatch `sys.platform`.
- **Windows and Mac are equals (owner's rule, 2026-10-31).** (1) The README's two download buttons always serve the newest version: both point at `releases/latest/download/` (`DepopSellerSetup.exe`, `DepopSeller-Mac.zip`), and all the release's files come from the same `release` run, so they always carry the same version. Pushing to `main` reaches no user by itself - run `release` (on the Windows machine, which has Inno Setup) after pushing anything users should get, and never publish a release missing one of them, or a button breaks. (2) Every feature works the same on both: a change that only works on one OS is not done, and where the mechanics must differ (installer vs zip, SmartScreen vs Gatekeeper, taskbar vs Dock) what the seller experiences must still match. Known gaps still to close: after **Update** a Mac closes and waits to be reopened instead of restarting itself (`updates.can_restart`), and Mac users install Python themselves while the Windows installer bundles it.
- Windows 11, PowerShell 5.1. `git` and `gh` are installed at `C:\Program Files\Git\cmd` and `C:\Program Files\GitHub CLI`; a fresh shell may need them appended to `$env:Path`.
- Python 3.14 (`python`). Project venv: `.venv` (`python -m venv .venv`; run with `.venv\Scripts\python.exe`). Dependencies live in `pyproject.toml`: `pillow`, `pillow-heif`, `anthropic`, `python-dotenv`. Playwright is the optional `automation` extra (the Depop button's automated-browser fallback) - neither setup nor the installer adds it, and without it `sell_open` answers "add the Chrome helper" instead of starting a job that could never run.
- **Python 3.12-3.14 only, not 3.15:** `onnxruntime` has no 3.15 wheel yet, so five places refuse 3.15 and point at 3.14 - see docs/architecture.md (Python versions) before changing any of them.
- Raw photos are iPhone `.HEIC` (square, ~4284×4284). Decoding needs `pillow-heif` (`pillow_heif.register_heif_opener()`).

## Check on a Mac

Features are built on Windows and checked on the MacBook afterwards. CI runs every test on a real Mac,
but it cannot see the screen - a system window that never appears, a permission prompt, the app icon,
setup, Gatekeeper or a download can only be confirmed by a person at a Mac. This list is how the two
machines hand that over; an empty list means the Mac side is fully checked.

- **On Windows:** when a change is visible or clickable on a Mac in a way the tests cannot prove (system
  dialogs, Finder / Trash, `desktop.py`, the `.app` bundle, `setup.sh`, the updater, the downloads), add a
  line here in the same commit: what to click, what should happen, the code concerned, and the version
  it first shipped in. Pure logic and page content need no line - CI covers them.
- **On the MacBook:** after `git pull`, work through the list with the owner: say what to click, check
  what can be checked directly, fix anything that does not work, delete each line once it works (with a
  short note in the commit message), and push.
- **Before a release (Windows):** if an unchecked line covers a change going into the release, say so
  before publishing. The owner decides; a change that only touches Windows code need not wait.

(Nothing waiting. Choose folder, Delete batch and Delete Depop Seller were checked on the MacBook before 1.1.6.)

## Data layout

**Two folders, kept apart** (`config.py`): the **app folder** (`PROJECT_ROOT`) is the software and
holds nothing personal, so it can be replaced or published; the **data folder** (`DATA_DIR`,
`~/DepopSeller`, overridden by `DEPOP_SELLER_DATA` or `data_dir` in the per-machine
`machine_config_file()`) holds everything of the seller's. That split is the whole reason moving to
another computer is one copy - never put seller data back in the app folder.
`migrate_into_data_dir()` moves an older install's `product_image`, `depop_seller.db`,
`description_style.md`, `style_history` and `.env` across once (called from `cli.main`, never
overwrites, a rename when both are on one drive), and `load_api_key` still reads the app folder's
`.env` as a fallback.

```
<data dir>/                       # ~/DepopSeller - the one folder a seller carries between machines
  product_image/<batch>/          # any safe folder name: a date, "Autumn knits", ... (or anywhere - see below)
  product_image/batches-elsewhere.json   # name -> folder of each batch kept outside product_image
    raw_image/      input HEIC — the app only ever *adds* files here (upload / import); existing photos are never modified, moved or deleted
    thumbs/         512 px JPEG cache (rebuilt on demand if missing)
    cache/          scan.json + cached model responses (generated)
    manifest.csv    one row per photo; the human-reviewed truth
    manifest.bak.csv  previous version, written by every save
    sort_image/     optional export: <item_id>_<photo_no>.jpg + manifest.csv — always copied, never moved
  depop_seller.db                 # local SQLite: items + photos per batch
  description_style.md            # the seller's own style, started from the app's template
  style_history/                  # previous versions of it
  .env                            # ANTHROPIC_API_KEY

<app folder>/                     # the software: code, launchers, the extension, the style template
```

## Conventions

- Python: type hints, `pathlib`, `argparse` CLI, stdlib `logging`; small modules (`scan`, `group`, `manifest`, `review`, `apply`).
- Idempotent and safe: re-running never destroys data; `--apply` refuses to write into a non-empty `sort_image/` unless `--force`.
- Tests in `tests/` (pytest) use tiny synthetic images, never the real photos. `ruff check .` and `mypy` must pass as well (rules in `pyproject.toml`); CI runs all three on Windows and macOS. Code for the other system gets `# type: ignore[attr-defined]`, never a changed platform check (tests fake the other system by patching `os.name` / `sys.platform`).
- Follow the Anthropic SDK patterns from the `claude-api` skill when touching `group.py` (no `budget_tokens`, no prefill; use `output_config` for structured output).
- **Shell gotchas:** the Bash tool turns `\n` (and backslashes) inside heredocs into real characters - write files with the Write tool, or build strings with `chr(10)` / `chr(92)`. In a page's JavaScript a real newline inside a quoted string stops the whole script from loading (`test_every_page_script_has_no_string_broken_across_lines`).
- `.claude/launch.json` (local, not committed) has `app-preview-8766`, which uses the seller's real data folder. For checks, use the demo folder from the `verify-ui` skill instead.
