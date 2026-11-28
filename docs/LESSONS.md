# Lessons

Depop Seller is built with Claude Code, and most of its rules exist because something went wrong
once. This page keeps the ones that changed how the project works. Each entry ends with what now
prevents it: a guard in the code, a test that runs on Windows and macOS for every push, and the rule
in [`CLAUDE.md`](../CLAUDE.md) that the agent works within.

## Descriptions were billed to the API instead of the subscription

**What happened (2026-09-20).** Descriptions are meant to run on the seller's Claude subscription
through the Claude Code CLI; the paid API key is only for grouping photos. Loading the key put it into
the process environment, the CLI inherited it, and it quietly billed the API instead (about $0.66).

**What changed.** Two independent layers. The key is read from `.env` without being exported, and the
CLI is started with every `ANTHROPIC_*` variable removed. Then the CLI's first event must report that
it uses no API key, or the run is stopped and its whole process tree killed.
Test: `test_claude_code_never_sees_the_api_key`.

**Lesson.** A billing rule written in a prompt or a doc is a hope. The rule has to be checked at the
moment the money would be spent.

## Depop blocked the automated browser

**What happened (2026-09-19).** The first version filled in Depop's listing form from a
Playwright-driven Chrome window. On its second run, Depop's bot protection answered 403.

**What changed.** The form is filled by a small Chrome extension running in the seller's own,
signed-in Chrome, with no automation flags. The Playwright path stays only as a fallback, and nothing
in the app ever presses Post: the seller checks the listing and posts it.

**Lesson.** Don't fight a site's bot protection. Work the way the user works, in their own browser,
and leave the final, public action to them.

## Chrome and Depop's page stopped the extension reaching the app

**What happened (2026-11-01).** Chrome's Local Network Access blocks websites from calling
`127.0.0.1`, and a consent script on Depop's page blocked unknown hosts, so the Depop tab could no
longer fetch photos from the app.

**What changed.** The Depop tab never calls the app. The extension's background worker does every
request and hands the results to the tab. The app accepts the extension's origin on two routes only,
one of them behind a single-use pass, and refuses every other site.
Test: `test_only_depop_gets_cors_and_other_sites_cannot_post`.

**Lesson.** Browsers keep tightening what pages may do. Put the cross-boundary work where the
platform allows it, rather than relying on a loophole that will close.

## A folder window that existed but never appeared

**What happened (2026-11-01).** On Windows, Choose folder opened Explorer's folder dialog from the
windowless app. Every window flag said the dialog was there and visible, but the seller saw nothing.
It was found only by capturing the real screen.

**What changed.** The dialog now belongs to a tiny, invisible, top-most window that is shown first,
and a change to any system dialog is checked by capturing the screen, not by reading window state.
Test: `test_the_folder_chooser_is_the_system_s_own_on_windows_and_mac`.

**Lesson.** For anything a person has to see, "the API says it is visible" is not evidence. Look.

## "Install Rosetta" on a new Mac

**What happened (2026-10-31, the first real download).** An Apple silicon Mac without Rosetta asked
to install Rosetta and never started the app. A macOS app whose main program is a script triggers
that, whatever its settings say. Earlier, a zip built on Windows had lost the executable bit and
produced the same message.

**What changed.** The app's main program is a tiny universal (arm64 + x86_64) binary that starts the
script, and the release zip sets file modes explicitly.
Test: `test_the_mac_app_starts_with_a_universal_program_not_a_script`.

**Lesson.** A message can name the wrong cause. Reproduce it on the real platform before fixing what
it says.

## The installer carried the build machine's folder paths

**What happened (2026-09-29).** A review of the published Windows installer found that its compiled
Python files recorded the full path of every source file on the machine that built it, including the
home folder. The installer was rebuilt and replaced.

**What changed.** Before packaging, every compiled file is rewritten with a path relative to the
install folder, the build's own smoke test adds no new ones, and the build refuses to finish if any
file still contains the home or project folder in any spelling.
Test: `test_the_bundle_never_names_a_folder_of_the_release_machine`.

**Lesson.** Review what you ship, not only what you commit. The repository was clean; the build
output was not.

## Pages that broke without an error

**What happened.** While descriptions were being written, the Sell page redrew every card every
2.5 seconds and wiped whatever the seller was typing in another card. Separately, a single line break
inside a JavaScript string stopped a whole page's script from loading, so the page sat at
"checking..." while the server answered normally.

**What changed.** The page redraws only the cards that changed, and never the one being typed in.
Every page's script is checked for broken strings.
Tests: `test_sell_page_generates_descriptions_for_the_ticked_items_only`,
`test_every_page_script_has_no_string_broken_across_lines`.

**Lesson.** The worst bugs make no noise. When one is found, write the test that would have caught it
silently failing.

## Knowing what not to ship: White Background

**What happened (2026-10-31).** White Background cut the clothes out of a photo onto plain white,
locally, with a model chosen after comparing three on real photos. It shipped in 1.1.0. Used on real
listings, the cut-outs were not good enough to sell with.

**What changed.** The feature is switched off by one flag. Its code and tests stay, originals are
shown and uploaded again, and its library stays installed on purpose, because removing it would have
forced every installed copy to download a new installer.
Test: `test_switched_off_the_app_hides_it_refuses_it_and_shows_originals`.

**Lesson.** A feature that works technically can still be wrong for the user. Turning it off cleanly
is part of building it.

## Letting the agent merge "low-risk" changes by itself

**What happened (2026-11-27).** To automate more, Claude Code was going to merge its own pull requests
when the changed files were on a list: first a list of risky files that had to wait for the owner,
then the other way round, a list of safe ones (docs, stylesheets, tests). Two independent reviews by
fresh agents took both apart. The risky list missed the code behind the app's own invariants (the
photo order, `.gitignore`, the key route). The safe list was not safe: a test change can skip tests
and turn CI green, the README holds the download buttons, a stylesheet ships to every user. And the
text-matching guard missed other ways of merging (`gh.exe`, the GitHub API, a push to `main`). One
real bug turned up too: a merge in the same command switched off the commit privacy check.

**What changed.** Everything up to the merge stays automatic, and a person approves every change
that reaches `main` - the industry norm. The guard now asks before any merge however it is spelled
and any push to `main`, stops `--admin` and `--auto`, and runs every check on every command, keeping
the strictest answer. Tests: `test_every_merge_and_every_push_to_main_waits_for_the_owner`,
`test_one_part_of_a_command_cannot_switch_off_another_check`.

**Lesson.** Automate the work, not the approval. And an independent reviewer earns its keep: both
reviews found what the author had not.

## Smaller ones

- **A black console window** opened on Generate Description, because Windows gives every console
  program started by a windowless app a window of its own. Every background program now starts
  without one, checked against a control run that did open a window.
  Test: `test_background_programs_start_without_a_console_window`.
- **A Claude app update moved Claude Code**, and every Generate Description said it was missing. The
  app now looks in the new place first and never relies on `PATH`.
  Test: `test_claude_code_is_found_where_the_windows_app_keeps_it_now`.
- **Reopening the app on a Mac** showed a window onto a server that had already gone, because the port
  stayed blocked after closing. Port reuse is now set per platform.
  Test: `test_a_second_copy_is_refused_but_reopening_after_closing_is_not`.

## What worked

- **Tests as the agent's safety net.** Every change, by me or by the agent, runs the whole suite on
  Windows and macOS, so refactors are safe to ask for.
- **Measuring the model instead of trusting it.** `learn` scores Claude's photo grouping against
  batches a person has reviewed: on a 438-photo batch the first pass matched the reviewer on every
  item boundary, and the merge pass found all 7 of the reviewer's merges plus 38 the reviewer had
  missed.
- **A human at every irreversible step.** The seller reviews the grouping and posts every listing;
  releases are published by hand; deleting a batch or the app asks first and goes to the Recycle Bin
  or Trash.
- **A handover list between machines.** What only a person at a Mac can confirm is written down in
  `CLAUDE.md` when it ships and ticked off on the MacBook.
