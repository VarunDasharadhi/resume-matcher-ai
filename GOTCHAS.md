# GOTCHAS

One line each, added the moment something burns a session.

This file is an index, not an archive. It is read by every session at startup and is size-capped
(see `.githooks/pre-commit`), so anything needing more than a line or two lives in
`docs/gotchas/<slug>.md` with a pointer left here. Every gotcha is still listed, so nothing gets
rediscovered the hard way; you only pay for the detail when it is actually relevant.

- Werkzeug's debug reloader child process can run under a completely different Python executable than the one that launched the parent server (seen here: parent was this repo's own venv, child resolved to `AppData\Roaming\uv\python\...`); it looks like a stray foreign process squatting on the dev port but is the live server correctly serving current code. Check the parent process's command line (`Get-CimInstance Win32_Process`) before killing anything that looks foreign on the port.
- AVG Antivirus on this machine intercepts and can corrupt outbound HTTPS from Python, surfacing as anything from `SSL: CERTIFICATE_VERIFY_FAILED` to an outright `avgMonFltProxy` permission error mid-response. It is per-venv, a new venv needs the fix reapplied, unless a folder- or domain-level AVG exception replaces the per-venv certifi-bundle patch.
- A `venv --clear` that hits a Windows file lock partway through can leave the venv silently corrupted (empty dist-info dirs, modules that partially import but are missing attributes). If a rebuild fails on a lock, don't assume the venv is still in its pre-rebuild state; verify before continuing.
