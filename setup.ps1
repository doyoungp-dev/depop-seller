# One-time setup on Windows: create the virtual environment and install the project.
# Right-click this file and choose "Run with PowerShell", or from a terminal in this folder:
#   powershell -ExecutionPolicy Bypass -File setup.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Say($text) { Write-Host "`n== $text" }

# Windows ships a stub called python.exe that only prints "Python was not found" and offers the
# Store. It looks like Python to Get-Command, so every candidate is judged by whether it can
# actually run, with its own noise suppressed - a real Store install lives in the same folder.
# 3.12 to 3.14 only: onnxruntime, one of the libraries, has no build for 3.15 yet, so the install
# would fail half-way. The py launcher runs the newest Python by default, so ask it by version.
# Probes may write to stderr ("No suitable Python runtime found"); in Windows PowerShell 5.1 that
# is an error record, and under "Stop" the first one would end the script before the next try.
function Runs($exe, [string[]]$arguments) {
    $ErrorActionPreference = "Continue"
    & $exe @arguments *> $null
    return $LASTEXITCODE -eq 0
}
$py = $null
$launcher = Get-Command "py" -ErrorAction SilentlyContinue
if ($launcher) {
    foreach ($version in @("3.14", "3.13", "3.12")) {
        if (Runs $launcher.Source @("-$version", "-c", "import sys")) {
            $py = (& $launcher.Source "-$version" -c "import sys; print(sys.executable)").Trim()
            break
        }
    }
}
if (-not $py) {
    # every match on PATH, not just the first: the Store stub usually comes before a real Python
    foreach ($cmd in @(Get-Command "python", "python3" -CommandType Application -All -ErrorAction SilentlyContinue)) {
        if (Runs $cmd.Source @("-c", "import sys; raise SystemExit(0 if (3, 12) <= sys.version_info[:2] <= (3, 14) else 1)")) {
            $py = $cmd.Source; break
        }
    }
}
if (-not $py) {
    Write-Host ""
    Write-Host "  Depop Seller needs Python 3.14, which this computer does not have yet."
    Write-Host "  (A newer Python such as 3.15 does not work with it yet.)"
    Write-Host ""
    Write-Host "  I am downloading the Python 3.14 installer. Open it; on its FIRST screen, tick"
    Write-Host "     [x] Add python.exe to PATH"
    Write-Host "  then click Install Now. When it finishes, double-click Depop Seller again."
    Write-Host ""
    Write-Host "  (If Windows offers you Python 3.14 from the Microsoft Store instead, that works too.)"
    Write-Host ""
    try { Start-Process "https://www.python.org/ftp/python/3.14.10/python-3.14.10-amd64.exe" } catch { }
    exit 1
}
Say "using $(& $py --version) at $py"

Say "creating .venv"
if (-not (Test-Path ".venv\Scripts\python.exe")) { & $py -m venv .venv }
& ".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
Say "installing depop_seller and its dependencies"
& ".venv\Scripts\python.exe" -m pip install --quiet -e .

& (Join-Path $PSScriptRoot "make_desktop_icon.ps1")

Write-Host @"

== Setup finished.

Open the app with the "Depop Seller" icon now on your Desktop - no console window
appears - and finish in its Settings tab:
  * your Anthropic API key   (pays for sorting photos into items)
  * the Claude sign-in       (writes descriptions, on your own subscription)
  * the Chrome helper        (puts the photos into Depop's form)

To stop the app: Settings -> Close Depop Seller.
"@
