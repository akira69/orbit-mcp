# Orbit MCP adapter

Build an independent, small adapter around the installed GitLab Orbit CLI so
desktop MCP clients on Windows and macOS can query repositories on a Linux
development host. The user authorized building, publishing a repository, and
delegated the fork/new-project choice. Public examples must contain no personal
paths, addresses, credentials, or repository inventory.

## Approaches

Existing GitLab MCP servers call hosted GitLab APIs; those do not satisfy local
offline code queries. Forking the removed local MCP implementation couples us to
old Orbit internals and its license. Chosen implementation: independently written
Python adapter using the official MIT-licensed MCP SDK and current Orbit CLI.
No GitLab implementation code is copied or redistributed.

## Contract

- Linux server, Python >=3.11, Orbit >=1.0.0 (initial tested version: 1.0.0).
- MCP stdio carried by OpenSSH; no HTTP listener, hosted account, or GitLab token.
- Four tools: repositories, search, context, index.
- TOML maps repository aliases to explicit Git checkout roots. Unknown aliases
  are errors. Context paths must resolve inside the selected root; only local
  files and line ranges are accepted. Search is fixed-string, repo-scoped.
- No arbitrary shell, SQL, remote GitLab targets, or client-selected executable.
- Commands use argv lists, bounded output, timeouts, and process cleanup.
- Indexing changes only Orbit's local index. Search/context may also refresh it.
- Treat repository files as trusted local inputs, not a sandbox for hostile code;
  ordinary SSH permissions still apply. Configure only repos meant for clients.
- GitLab Orbit remains separately installed and licensed. No guarantee of token
  savings. Client-only files are invisible unless copied or checked out here.

## Delivery

Public MIT adapter repository, automated tests/CI, generic Windows/macOS SSH
configuration, installed devbox launcher and private config, real CLI and MCP
smoke test. No laptop configuration changes without access to those machines.
