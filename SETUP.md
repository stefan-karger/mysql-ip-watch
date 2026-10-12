# Exact setup instructions

## 1. Open the configuration file

Edit **`config.json` in the same folder as `watch.py` and `run.cmd`**.
All investigation settings go here. You do not need to edit the Python script.

`config.json` holds your live settings and is excluded from Git. Setup creates
it from the versioned `config.example.json` only if it is missing. To create it
manually, run this once before editing your settings:

```powershell
Copy-Item .\config.example.json .\config.json
```

The example file contains local XAMPP defaults:

```json
{
  "mysql": {
    "host": "127.0.0.1",
    "port": 3306,
    "user": "root",
    "password": "",
    "tls_ca": null
  },
  "target_ip": "127.0.0.1",
  "interval_seconds": 1,
  "max_hours": 168,
  "include_idle": false,
  "hostname_aliases": {"localhost": "127.0.0.1"}
}
```

## 2. Enter the database details and the suspect's IP

| Exact field in config.json | What to enter | Example |
| --- | --- | --- |
| `mysql.host` | Address/name of the **database server** the script connects to. Keep `127.0.0.1` if the server runs on this Windows machine. | `"db.company.example"` |
| `mysql.port` | Server's MySQL port, as a number. | `3306` |
| `mysql.user` | **Monitoring login used by this script**, with permission to see every user's connections. This is not the suspect's login. | `"root"` or `"ip_watch"` |
| `mysql.password` | Password for the monitoring login, inside quotes. Local XAMPP default is an empty string. | `"your-password"` or `""` |
| `target_ip` | **Suspect's client/source IP**, as the database server sees it. This is not the database server's address unless both happen to be the same. | `"192.168.10.42"` |
| `interval_seconds` | How many seconds between samples. Start with `1`; see the interval guidance below before lowering it. Minimum accepted value `0.05`. | `1` |
| `max_hours` | How long this invocation runs before stopping. Maximum `168` = seven days. | `168` or `24` |
| `include_idle` | `false`: capture running SQL only. `true`: also capture matching idle connections once per observed idle period, with `query: null`. | `false` |
| `hostname_aliases` | Map server-reported hostnames to their known client IPs. Details below. | `{"office-pc": "192.168.10.42"}` |
| `mysql.tls_ca` | Usually leave `null`. If your server requires verified TLS, put the CA PEM file path here; relative paths start at the config file's directory. | `"certs/company-ca.pem"` |

The script captures **every database username querying from `target_ip`** and
records that username in each event's `user` field. It does not filter by a
separate suspect-username field. For NAT/proxies/shared clients, the IP visible
to MySQL may be shared by several people.

Use valid JSON: double quotes around strings, no comments and no trailing comma
after the final field. Escape Windows backslashes (`"C:\\certs\\ca.pem"`) or
use forward slashes (`"C:/certs/ca.pem"`). Stop/restart after editing settings.

### Choose a polling interval

**Start with `"interval_seconds": 1`.** For this one-week investigation, try
`0.5` only if database CPU and application response times remain stable during
busy periods. Compare monitoring off and on under similar workloads. Avoid
`0.1` or faster without measuring the real server; the minimum accepted setting
of `0.05` is a validation limit, not a recommended interval.

The script reuses one connection and sends one process-list query per successful
poll. It reads all connections before filtering by IP, so the cost depends on
the server's connection count and workload. MariaDB documents that this
process-list access uses locking:
[MariaDB process-list documentation](https://mariadb.com/docs/server/reference/sql-statements/administrative-sql-statements/show/show-processlist).
Polls run sequentially; slow responses and reconnects reduce sampling frequency.

| Interval | Intended polls per second | Approximate chance of catching one 50 ms query |
| --- | --- | --- |
| `1` second | 1 | 5% |
| `0.5` seconds | 2 | 10% |
| `0.1` seconds | 10 | 50% |

These are mathematical estimates, not measurements. They assume regularly
spaced snapshots and a query starting at a random point between them. For a
query shorter than the interval, the approximate chance is its duration divided
by the interval. A query can start and finish entirely between polls. Running
for a week increases opportunities to observe repeated activity but does not
guarantee capturing an isolated short query.

Set `"include_idle": true` if detecting the suspect IP's connection is also
useful. An idle event has `query: null`; it cannot recover SQL missed between
polls. **An empty log does not prove the client never queried the database.**

For more complete evidence of brief queries, use server-side audit or general
query logging. MySQL's general query log records SQL statements when received,
without needing to sample their execution:
[MySQL general query log documentation](https://dev.mysql.com/doc/refman/8.4/en/query-log.html).
Logging adds work and consumes disk space, so measure its impact and monitor log
growth on the real server. This script does not enable server-side logging.

### When MySQL shows a hostname instead of an IP

Local XAMPP commonly shows `localhost:port`, so the supplied alias covers
`127.0.0.1`. For a remote client reported as `office-pc:port`, use:

```json
"hostname_aliases": {
  "localhost": "127.0.0.1",
  "office-pc": "192.168.10.42"
}
```

Use the exact hostname shown by the server, without its port. Matching is
case-insensitive for names. The script reports unmapped names in `watcher.log`;
add their known IPs here. It does not perform DNS lookups during sampling.
If targeting IPv6 loopback, set both `target_ip` and the `localhost` alias to
`"::1"`. A resolved name alone does not distinguish IPv4 from IPv6.

### Password alternative

You can leave `mysql.password` empty and set the password in the PowerShell
session from which you launch the script:

```powershell
$env:MYSQL_WATCH_PASSWORD = 'your-password'
.\run.cmd --check
.\run.cmd
```

`MYSQL_WATCH_PASSWORD` always overrides `mysql.password`, even if its value is
empty. Remove that session override with
`Remove-Item Env:\MYSQL_WATCH_PASSWORD` to use the file password again.

## 3. Check access and start

Open PowerShell in this folder. Install Python and the requirements first,
unless setup has already completed:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1
```

With `uv` installed, setup downloads Python 3.11 if needed and creates a local
`.venv`. See the installation details below for the alternative using `py`.
Then check database access:

```powershell
.\run.cmd --check
```

Success prints `Connection OK; all-user PROCESS visibility OK`. Check the target
and hostname aliases first; zero matching connections is normal when the client
is not currently running SQL. Unknown hostname warnings need investigation.

Then start the actual investigation:

```powershell
.\run.cmd
```

Leave the terminal open. Keep the machine awake and connected to the network.
It stops after `max_hours`, or press **Ctrl+C** to stop early. There is no
background service or second stop command. Double-clicking `run.cmd` also starts
the investigation with `config.json`.

To keep a separate configuration:

```powershell
Copy-Item .\config.json .\config.local.json
.\run.cmd --check --config .\config.local.json
.\run.cmd --config .\config.local.json
```

Edit `config.local.json` with your investigation settings before the check and
run commands. Both `config.json` and `config.local.json` are excluded from Git;
`config.example.json` contains the versioned local XAMPP example defaults.

Connection and read timeouts are fixed at five seconds. Temporary connection
failures retry with delays of 1, 2, 4, 8, 16 and then 30 seconds. Authentication
or permission errors exit so that you can correct the settings. An in-flight
operation can finish after the configured time limit by its network timeout.
A second copy in this folder is rejected to prevent duplicate output.

### If the monitoring login cannot see other users

An administrator can give the monitoring account the required visibility:

```sql
GRANT PROCESS ON *.* TO 'ip_watch'@'WATCHER_MACHINE_IP';
```

Use the actual monitoring account and account-host restriction in that command.
The account must already exist. The permission must be granted directly in this
script; it does not expand role-only privileges. The script itself runs
read-only inspection statements and does not grant permissions or block clients.

## 4. Find and read the results

Output paths are fixed relative to **this tool's folder**, regardless of where
you launch it:

| File | Contents |
| --- | --- |
| `data/queries.jsonl` | Captured evidence: timestamp, process ID, database username, client host, database, state, full available SQL and complete raw process row. |
| `data/watcher.log` | Start, connection, retry and capture messages. A `Polling OK` heartbeat appears roughly every minute after successful samples. |
| `data/queries.jsonl.lock` | Automatic single-instance lock. You can ignore it; its existence alone does not mean a watcher is running. |

Open `queries.jsonl` in a text editor. Each line is one JSON event. Newlines
inside SQL are escaped, so multiline SQL remains inside one JSON line. For a
readable PowerShell view:

```powershell
Get-Content .\data\queries.jsonl |
  ForEach-Object { $_ | ConvertFrom-Json } |
  Select-Object captured_at_utc, process_id, user, host, database, query |
  Format-List
```

The `query` field is the SQL to inspect. `process` preserves all original server
columns; binary fields are kept as Base64 objects. The timestamp is when the
query was observed, not its exact start or finish time. Older MariaDB Unicode
substitutions are recovered when its binary query field proves the original text.

Logs append if you start the script again. Duplicate tracking is **in memory
for the current run**. A long-running query appears once during that run;
restarting can record it again. On MariaDB, later identical executions get their
own records through query IDs. On MySQL, an identical execution whose boundary
falls between samples can be merged with the earlier record.

An empty log means **no matching query was observed**. Short queries can finish
between samples, so an empty file does not prove there was no database use.
If you need every executed statement, use a server audit/general query log.
The script also cannot reconstruct SQL/parameters the server does not expose.

Keep the files after the investigation; SQL can include sensitive values.

## Install on a different Windows machine

Install `uv` and extract the release ZIP, then:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1
```

Setup uses `uv` to download Python 3.11 if needed, create `.venv` in this folder,
and install the pinned driver/authentication dependencies there. The packages
are isolated from other projects, similar to a Node application's local
`node_modules`. The base Python interpreter lives in uv's per-user directory.
Setup needs internet access initially and changes no global execution policy.
It also creates `config.json` from `config.example.json` if missing, preserving
existing settings. Then complete steps 1–3 above.

Without `uv`, install Python 3.11 with the Windows `py` launcher before running
setup. To choose another version, such as Python 3.13, when creating a new
environment:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1 -PythonVersion 3.13
```

Setup reuses an existing `.venv`; `-PythonVersion` applies when creating it.

No virtual environment activation is needed. Do not copy an installed `.venv`
to another computer; run setup there. Exit code `0` means successful completion
or Ctrl+C; `2` means configuration, permissions, file access or database failure.
