# orbit-mcp

Use GitLab Orbit's **local code graph** from MCP clients on Windows and macOS,
connected to a Linux development server over SSH.

This independent adapter runs the separately installed `orbit` CLI. It is not
an official GitLab product and includes no GitLab source or binaries. Local
queries need no GitLab account, API token, paid hosted graph, or GitLab server.
Token savings depend on the task and have not been benchmarked.

## Tools

| Tool | Purpose |
| --- | --- |
| `orbit_repositories` | List the operator-configured repository aliases |
| `orbit_search` | Literal, regex, or definition search; optional relative path scope |
| `orbit_context` | Batch file ranges and named symbols with indexed relationships |
| `orbit_index` | Start/reuse a detached index; optional bounded foreground mode |
| `orbit_status` | Inspect worker, manifest, commit and working-tree state |

Context targets look like `src/app.py`, `src/app.py:10-80`, or
`symbol:calculate`. Up to 20 targets can be read in one call. Bare files default
to lines 1–200; explicit ranges allow up to 1000 lines. Symbols return their
definition and indexed connections. Search defaults to literal text; regex
mode excludes colons and definitions mode accepts names/words. These constraints
prevent queries from switching to GitLab's remote target syntax.

Orbit may widen the optional search path scope when no matches are found.
The configured repository, not that filter, is the access boundary.

## Background indexing and status

Call `orbit_index` with `{"repository":"myproject"}`. It returns after Orbit's
startup handshake, rather than waiting for the whole index. Repeated calls reuse
an observed live worker; simultaneous starts may return `busy`. Then poll
`orbit_status` for the same alias. Jobs survive MCP/SSH disconnects, and the next
connection can inspect them. No extra daemon is installed.

Status distinguishes `indexing`/`queued_or_indexing`, `indexed`, `stale`,
`not_indexed`, and `unknown`. It reports worker liveness separately
from Orbit's saved manifest. PID identity includes process start time and boot
ID, so a reused PID does not count as the original worker. `dirty` reports
uncommitted/untracked files; `working_tree_freshness` remains `unverified` because
Orbit exposes no full working-tree freshness fingerprint.

**An indexed manifest does not prove the latest refresh succeeded.** Orbit's
detached child does not expose a recoverable exit code to this adapter. An
unobserved worker or an interrupted startup is reported conservatively. Worker
liveness refers to the last adapter request; a later external job may be running.
An initially queued worker may have started, so its current phase is reported as
`queued_or_indexing`. Check
status before retrying a timed-out start; do not reset the graph. Use source
queries to check the content you need. Progress percentages are unavailable.

Set `background:false` to use the original bounded foreground index command.
The default changed to background indexing in 0.2.0.

Job observations live in `$XDG_STATE_HOME/orbit-mcp` (default
`~/.local/state/orbit-mcp`), or the configured `state_dir`. New directories and
records are private. Connections must use the same Unix account, configuration,
and Orbit data environment to share jobs. Status never returns another
repository's manifest or raw index logs. Large workspace manifests may require
raising `max_output_bytes`; truncated JSON is an error, not a partial status.

## Install on the server

Requires Linux, Python 3.11+, Git, and a separately installed
[GitLab Orbit CLI](https://docs.gitlab.com/orbit/cli/) under its applicable license.
Tested with Orbit 1.0.0.

```sh
git clone https://github.com/akira69/orbit-mcp.git
cd orbit-mcp
python3 -m venv .venv
.venv/bin/pip install .
mkdir -p ~/.config/orbit-mcp
cp config.example.toml ~/.config/orbit-mcp/config.toml
```

Edit the local config: set the absolute Orbit executable path and map aliases
to Git checkout roots. A repository needs an initial commit for Orbit indexing.
Git worktrees are supported. Add each checkout explicitly; no home-directory
discovery occurs. Keep real paths and credentials out of this repository.

```sh
/absolute/path/orbit-mcp/.venv/bin/orbit-mcp --config /absolute/path/config.toml
```

The process waits silently for MCP input. It needs no systemd service,
background daemon, HTTP listener, or extra network port.

## Diagnose a connection

```sh
orbit-mcp --config /absolute/path/config.toml --check
```

This prints JSON and exits 0 on success or 1 on failure. It checks executable
version, repository roots and initial commits, writable adapter state, and a
real MCP subprocess handshake with five-tool discovery and a repository-list
call. It does not index or modify checkouts. Orbit 1.0.0 is the tested version;
the report shows the installed version so upgrades can be assessed explicitly.

Run the same check over SSH from **each** desktop to verify that SSH route:

```sh
ssh -T -o BatchMode=yes orbit-devbox /absolute/path/orbit-mcp/.venv/bin/orbit-mcp --config /absolute/path/config.toml --check
```

A successful server-side check does not establish that a particular desktop app
has loaded its MCP configuration. Restart that client and call
`orbit_repositories` there too.

## Connect from macOS or Windows

Your MCP client must support launching a **stdio command**; clients accepting
only HTTP URLs cannot use this transport. The server remains Linux. The desktop
needs OpenSSH and key-based access to that host.

Add an alias to `~/.ssh/config` on macOS or `%USERPROFILE%\.ssh\config` on Windows:

```sshconfig
Host orbit-devbox
    HostName devbox.example.net
    User your-user
    IdentityFile ~/.ssh/id_ed25519
    IdentitiesOnly yes
    BatchMode yes
    StrictHostKeyChecking yes
```

Replace the host, user, and key path. First establish and verify the host key
interactively using your real hostname, then verify `ssh orbit-devbox true`.
An encrypted key must be unlocked in the desktop's SSH agent. Do not disable
host-key checks.

Add this to the client's MCP configuration, substituting the real **server-side**
executable and config paths:

```json
{
  "mcpServers": {
    "orbit-devbox": {
      "command": "ssh",
      "args": [
        "-T", "-o", "BatchMode=yes", "orbit-devbox",
        "/absolute/path/orbit-mcp/.venv/bin/orbit-mcp",
        "--config", "/absolute/path/config.toml"
      ]
    }
  }
}
```

Use launch paths without spaces, or a server-side wrapper. On Windows, if the
app cannot find `ssh`, use `C:\\Windows\\System32\\OpenSSH\\ssh.exe` as the JSON
command. Do not use `-t`: a pseudo-terminal corrupts MCP traffic. Noninteractive
remote shell startup scripts must not print banners to stdout.

For Codex CLI, register the same command with:

```sh
codex mcp add orbit-devbox -- ssh -T -o BatchMode=yes orbit-devbox /absolute/path/orbit-mcp/.venv/bin/orbit-mcp --config /absolute/path/config.toml
```

Restart the client, then ask it to call `orbit_repositories` and query an alias.
This reads the **server's checkout**. Laptop-only edits are invisible until
copied or checked out there. Any reachable LAN/VPN SSH host works.

## Limits and trust

- Configure only trusted checkouts intended for the client. Tracked secrets and
  indexed code are accessible. This is not a sandbox for hostile repositories
  or a multi-tenant authorization system.
- Use an SSH account with only the access it needs. MCP aliases do not restrict
  that account's ordinary SSH shell permissions.
- Context file targets must be tracked and resolve inside the selected root.
  Search follows Orbit's handling of working-tree and ignored files.
- No arbitrary shell, SQL, global graph IDs, or hosted GitLab targets.
- Commands serialize per connection; Orbit handles cross-process index locks.
  Timeouts and cancellation kill/reap the foreground command process group.
  Explicit background indexes survive disconnects. Use them for large repos;
  foreground timeout is configurable up to 600 seconds.
- Search/context/foreground-index responses contain `output` and `truncated`.
  Background/status responses contain state fields. Narrow queries when truncated.
  A truncated index response is not proof that indexing completed.
- GitLab API credential environment variables are removed from child processes;
  telemetry is disabled for each command. This is not a network sandbox:
  operator-managed Orbit/glab configuration still matters.

## Update and test

```sh
git pull --ff-only
.venv/bin/pip install --upgrade .
```

Update Orbit separately. See [compatibility notes](docs/compatibility.md).
The [upstream findings](docs/upstream-findings.md) link prerelease issues and
release notes to implemented safeguards and the next feature priorities.

```sh
.venv/bin/pip install -e '.[dev]'
.venv/bin/ruff check .
.venv/bin/pytest -q
ORBIT_INTEGRATION=1 .venv/bin/pytest -q
```

Default tests use a controlled executable fixture and real MCP stdio. The opt-in
integration test uses real Orbit with a disposable Git repo and index, verifies
background indexing across reconnects, search modes, caller context, and
uncommitted-file refresh. `scripts/probe_upstream.py` records additional small
language-resolution observations using disposable repositories. CI runs
default tests on Python 3.11/3.13. This adapter is MIT licensed; Orbit is separate.
