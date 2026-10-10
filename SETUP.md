# Exact setup instructions

## 1. Open the configuration file

Edit **`config.json` in the same folder as `watch.py` and `run.cmd`**.
All investigation settings go here. You do not need to edit the Python script.

The supplied file contains working local XAMPP defaults:

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
| `interval_seconds` | How many seconds between samples. Keep `1`, or use `0.5` for more frequent sampling. Minimum `0.05`. | `1` |
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

Open PowerShell in this folder. Setup is already installed on this machine:

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
run commands. This file is excluded from Git; `config.json` contains the tracked
local XAMPP example defaults.

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

Install Python 3.11 or newer with the `py` launcher. Extract the release ZIP, then:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1
```

This creates `.venv` and installs the pinned driver/authentication dependencies.
It needs internet access for initial setup. It changes no global execution
policy. Then complete steps 1–3 above. If you have Python 3.13 instead:

```powershell
.\setup.ps1 -PythonVersion 3.13
```

No virtual environment activation is needed. Do not copy an installed `.venv`
to another computer; run setup there. Exit code `0` means successful completion
or Ctrl+C; `2` means configuration, permissions, file access or database failure.
