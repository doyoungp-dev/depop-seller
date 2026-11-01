#!/bin/bash
# Depop Seller, macOS launcher - and, the first time, the installer.
#
# macOS starts the compiled `depop-seller` next to this file (installer/mac_launcher.c), which
# hands over to this script: an app whose main program is a script makes an Apple silicon Mac
# ask for Rosetta instead of running it.
#
# Double-click this app in Finder. If the app has not been set up on this Mac yet it sets itself
# up (about a minute), then opens; after that it just opens. There is no Terminal window at any
# point, and nothing else to double-click.
#
# Normally the bundle sits in the project folder and finds it by walking up out of
# Depop Seller.app/Contents/MacOS. Copy the app to the Desktop, the Dock or /Applications and it
# falls back to the path setup.sh recorded, so it still works from anywhere.
#
# Everything runs inside main(), called on the last line: bash reads a script as it goes, and
# Check for updates may rewrite this file while the app is open. A function is read whole first.
set -u

LOG="$HOME/Library/Logs/Depop Seller.log"
RECORDED="$HOME/Library/Application Support/Depop Seller/project-path"
PYTHON_PKG="https://www.python.org/ftp/python/3.14.10/python-3.14.10-macos11.pkg"   # official, signed by the PSF

fail() {
    /usr/bin/osascript -e "display dialog \"$1\" buttons {\"OK\"} default button 1 with icon caution with title \"Depop Seller\"" >/dev/null 2>&1
    exit 1
}

note() {
    /usr/bin/osascript -e "display notification \"$1\" with title \"Depop Seller\"" >/dev/null 2>&1
}

is_project() {
    [ -n "${1:-}" ] && [ -f "$1/depop_seller/__init__.py" ] && [ -f "$1/setup.sh" ]
}

# A downloaded app that has not been moved is started by macOS from a random read-only copy
# ("App Translocation"), so walking up finds nothing. Spotlight still knows where it was unzipped.
find_unzipped() {
    local app dir best="" best_time=0 when
    while IFS= read -r app; do
        case "$app" in */AppTranslocation/*) continue ;; esac
        dir="$(dirname "$app")"
        is_project "$dir" || continue
        when="$(stat -f %m "$dir" 2>/dev/null || echo 0)"
        if [ "$when" -gt "$best_time" ]; then best="$dir"; best_time="$when"; fi
    done < <(/usr/bin/mdfind 'kMDItemFSName == "Depop Seller.app"' 2>/dev/null)
    printf '%s' "$best"
}

ask_for_folder() {
    local picked
    picked="$(/usr/bin/osascript -e 'POSIX path of (choose folder with prompt "Where is Depop Seller? Choose the folder you unzipped - the one with Depop Seller inside it.")' 2>/dev/null)" || return 1
    printf '%s' "${picked%/}"
}

main() {
    mkdir -p "$(dirname "$LOG")"

    # An app opened from Finder gets a bare PATH (/usr/bin:/bin:/usr/sbin:/sbin), which holds no
    # Python new enough. Add where python.org and Homebrew put theirs, newest first.
    local dir
    for dir in /usr/local/bin /opt/homebrew/bin \
               /Library/Frameworks/Python.framework/Versions/3.1[2-9]/bin; do
        [ -d "$dir" ] && PATH="$dir:$PATH"
    done
    export PATH

    local here
    here="$(cd "$(dirname "$0")/../../.." 2>/dev/null && pwd)"
    if ! is_project "$here" && [ -f "$RECORDED" ]; then
        here="$(cat "$RECORDED")"
    fi
    if ! is_project "$here"; then
        here="$(find_unzipped)"
    fi
    if ! is_project "$here"; then
        here="$(ask_for_folder)" || exit 1
        is_project "$here" || fail "That folder does not hold Depop Seller.\n\nChoose the folder you unzipped - the one with Depop Seller inside it."
    fi
    cd "$here" 2>/dev/null || fail "Could not open the Depop Seller folder:\n$here"

    exec >>"$LOG" 2>&1
    echo "--- $(date '+%Y-%m-%d %H:%M:%S') starting in $here"

    # ------------------------------------------------------------ first run: set ourselves up
    if [ ! -x ".venv/bin/python" ]; then
        echo "no .venv yet - running setup"
        # Apple's own /usr/bin/python3 is too old and, without the developer tools, pops up an
        # offer to install them - so only versioned names, which it never answers to. 3.14 first:
        # the version the tests run on. Not 3.15 yet: onnxruntime, one of the libraries, has no
        # build for it, so setup would fail half-way (see CLAUDE.md).
        local py="" candidate
        for candidate in python3.14 python3.13 python3.12; do
            if command -v "$candidate" >/dev/null 2>&1 &&
               "$candidate" -c 'import sys; raise SystemExit(0 if (3, 12) <= sys.version_info[:2] <= (3, 14) else 1)'; then
                py="$candidate"
                break
            fi
        done
        if [ -z "$py" ]; then
            /usr/bin/osascript -e 'display dialog "Depop Seller needs Python 3.14, which this Mac does not have yet. (A newer Python such as 3.15 does not work with it yet.)\n\nClick Download: the Python 3.14 installer goes to your Downloads. Open it, click Continue through it, then double-click Depop Seller again." buttons {"Download", "Cancel"} default button 1 with title "Depop Seller"' >/dev/null 2>&1 \
                && open "$PYTHON_PKG"
            exit 1
        fi
        note "Setting up - this takes a minute or two."
        if ! DEPOP_PYTHON="$py" bash setup.sh; then
            fail "Setup did not finish.\n\nThe details are in:\n$LOG"
        fi
        note "Ready - opening Depop Seller."
    fi

    [ -x ".venv/bin/python" ] || fail "Setup has not finished.\n\nThe details are in:\n$LOG"

    DEPOP_QUIET=1 .venv/bin/python -m depop_seller hub &
    local pid=$! status
    trap 'kill "$pid" 2>/dev/null' TERM INT     # Cmd+Q in the dock stops the server
    wait "$pid"
    status=$?

    case "$status" in
        0|130|143) ;;                            # normal exit, Ctrl+C, or quit from the dock
        *) fail "Depop Seller stopped unexpectedly (exit $status).\n\nThe log is at:\n$LOG" ;;
    esac
}

main "$@"
exit
