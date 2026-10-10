# MySQL IP Watch 1.1.0

A small Windows script for a one-off investigation lasting up to one week.
It polls MySQL/MariaDB for one client IP and writes observed queries directly
to `data/queries.jsonl`, including process ID, database user and every raw
process-list field. Long-running queries are logged once during the current run.

**Start with [SETUP.md](SETUP.md).** It shows exactly which fields to change,
where the password goes, how to start/stop and where to find the results.

Install from GitHub:

```powershell
git clone https://github.com/stefan-karger/mysql-ip-watch.git
cd mysql-ip-watch
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1
```

```powershell
.\run.cmd --check
.\run.cmd
```

Default: local XAMPP, root/empty password, target `127.0.0.1`, polling every
one second, automatic stop after 168 hours. Ctrl+C stops it earlier. Keep the
terminal open and the computer awake while investigating.

For investigation-specific settings, copy `config.json` to `config.local.json`
and launch with `--config .\config.local.json`. The local settings, installed
environment and runtime logs are excluded from Git.

This is process-list sampling. It can miss queries that finish between samples;
an empty log does not prove that the client never queried the server. Restarting
the script resets duplicate tracking and can record an ongoing query again.

## Implementation choices

| Component | Purpose |
| --- | --- |
| Python and PyMySQL | A readable Windows script and a MySQL-compatible driver. Pinned authentication dependencies support modern MySQL logins; a local virtual environment keeps installation separate from other applications. |
| JSON configuration | Server credentials, target IP and sampling settings can be edited without changing code. Validation catches unknown fields and invalid values. |
| Exact IP matching and hostname aliases | Normalized addresses avoid substring matches; explicit aliases handle names reported by the server without DNS requests in the polling loop. |
| Full process-list inspection | MariaDB exposes query IDs and binary SQL; MySQL uses SHOW FULL PROCESSLIST. Direct PROCESS permission is checked so other users' connections are visible. |
| In-memory duplicate tracking | One continuous investigation needs only the latest successful observation per connection. Query IDs distinguish MariaDB executions; MySQL uses observed statement boundaries. Failed samples preserve tracking. |
| Append-only JSONL | Each event contains a UTC timestamp, convenient query fields and every raw process column. Binary data uses Base64; MariaDB Unicode recovery preserves supported four-byte characters. |
| Foreground operation and fixed output paths | The terminal shows progress, Ctrl+C stops early, and the time limit ends the investigation automatically. Results are always in this folder's data directory. |
| Timeouts, retries, heartbeat and OS lock | Five-second network timeouts and retries capped at 30 seconds handle interruptions. A minute heartbeat shows successful sampling; the Windows lock prevents duplicate launches. |
| Optional verified TLS | A configured CA certificate enables server certificate and hostname verification for remote connections. |
| Setup and launcher scripts | PowerShell installs the pinned dependencies; run.cmd selects the local interpreter and works from Windows shells or a double-click. |
