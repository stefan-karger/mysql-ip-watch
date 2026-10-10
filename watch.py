"""Poll one client's MySQL connections for a short, one-off investigation."""
from __future__ import annotations

import argparse
import base64
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
import ipaddress
import json
import logging
import math
import msvcrt
import os
from pathlib import Path
import re
import sys
import time

import pymysql


VERSION = "1.1.0"
ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
QUERY_LOG = DATA / "queries.jsonl"


def normalize_ip(value):
    address = ipaddress.ip_address(value)
    return str(address.ipv4_mapped or address) if isinstance(address, ipaddress.IPv6Address) else str(address)


def load_config(path):
    path = Path(path).resolve()
    try:
        config = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"Cannot read valid JSON configuration: {path}") from exc
    defaults = {"target_ip": "127.0.0.1", "interval_seconds": 1, "max_hours": 168,
                "include_idle": False, "hostname_aliases": {"localhost": "127.0.0.1"}, "mysql": {}}
    if not isinstance(config, dict) or config.keys() - defaults.keys():
        raise ValueError("Unknown configuration fields; follow SETUP.md")
    config = defaults | config
    db_defaults = {"host": "127.0.0.1", "port": 3306, "user": "root", "password": "", "tls_ca": None}
    if not isinstance(config["mysql"], dict) or config["mysql"].keys() - db_defaults.keys():
        raise ValueError("Unknown mysql fields; follow SETUP.md")
    config["mysql"] = db_defaults | config["mysql"]
    db = config["mysql"]
    for key in ("host", "user", "password"):
        if not isinstance(db[key], str) or (key != "password" and not db[key]):
            raise ValueError(f"mysql.{key} must be a {'nonempty ' if key != 'password' else ''}string")
    if type(db["port"]) is not int or not 1 <= db["port"] <= 65535:
        raise ValueError("mysql.port must be an integer between 1 and 65535")
    for key, upper in (("interval_seconds", 86400), ("max_hours", 168)):
        value = config[key]
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= upper:
            raise ValueError(f"{key} must be greater than zero and no more than {upper}")
    if config["interval_seconds"] < 0.05:
        raise ValueError("interval_seconds must be at least 0.05")
    if type(config["include_idle"]) is not bool:
        raise ValueError("include_idle must be true or false")
    if not isinstance(config["target_ip"], str):
        raise ValueError("target_ip must be an IP address string")
    config["target_ip"] = normalize_ip(config["target_ip"])
    aliases = config["hostname_aliases"]
    if not isinstance(aliases, dict) or any(not isinstance(v, str) or not k for k, v in aliases.items()):
        raise ValueError("hostname_aliases must map hostnames to IP address strings")
    config["hostname_aliases"] = {host.lower().rstrip("."): normalize_ip(ip) for host, ip in aliases.items()}
    if db["tls_ca"] is not None:
        if not isinstance(db["tls_ca"], str) or not db["tls_ca"]:
            raise ValueError("mysql.tls_ca must be null or a CA certificate path")
        ca = (path.parent / db["tls_ca"]).resolve()
        if not ca.is_file():
            raise ValueError(f"TLS CA file not found: {ca}")
        db["tls_ca"] = str(ca)
    return config


def client_host(value):
    value = (value or "").strip()
    if value.startswith("[") and "]" in value:
        return value[1:value.index("]")]
    host, separator, port = value.rpartition(":")
    return host if separator and port.isdecimal() and value != "::1" else value


def matching_rows(rows, config, own_id, warned):
    matches = []
    for row in rows:
        if int(row["ID"]) == own_id:
            continue
        host = client_host(row.get("HOST"))
        if not host:
            continue
        try:
            address = normalize_ip(host)
        except ValueError:
            address = config["hostname_aliases"].get(host.lower().rstrip("."))
            if address is None and host not in warned:
                logging.warning("Unmapped hostname %r; see hostname_aliases in SETUP.md", host)
                warned.add(host)
        if address == config["target_ip"] and (config["include_idle"] or row.get("INFO") is not None):
            matches.append(row)
    return matches


def query_text(row):
    # Older MariaDB INFO uses utf8mb3; recover emoji from original UTF-8 bytes
    # only when INFO agrees with its known substitution. Preserve all raw data.
    text, binary = row.get("INFO"), row.get("INFO_BINARY")
    if text is None or not isinstance(binary, bytes):
        return text
    try:
        decoded = binary.decode("utf-8")
    except UnicodeDecodeError:
        return text
    downgraded = "".join("?" * len(ch.encode("utf-8")) if ord(ch) > 0xFFFF else ch for ch in decoded)
    return decoded if decoded == text or downgraded == text else text


def connect(config):
    db = config["mysql"]
    options = dict(host=db["host"], port=db["port"], user=db["user"],
                   password=os.environ.get("MYSQL_WATCH_PASSWORD", db["password"]),
                   charset="utf8mb4", autocommit=True, connect_timeout=5,
                   read_timeout=5, write_timeout=5, cursorclass=pymysql.cursors.DictCursor)
    if db["tls_ca"]:
        options.update(ssl_ca=db["tls_ca"], ssl_verify_cert=True, ssl_verify_identity=True)
    connection = pymysql.connect(**options)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SHOW GRANTS")
            for row in cursor.fetchall():
                grant = re.search(r"^GRANT\s+(.+?)\s+ON\s+\*\.\*\s+TO\s", str(next(iter(row.values()))), re.I)
                if grant and {p.strip().upper() for p in grant[1].split(",")} & {"PROCESS", "ALL", "ALL PRIVILEGES"}:
                    break
            else:
                raise ValueError("Monitoring account needs PROCESS granted directly ON *.*; see SETUP.md")
            cursor.execute("SELECT VERSION() AS version")
            version = cursor.fetchone()["version"]
            cursor.execute("SHOW GLOBAL STATUS LIKE 'Uptime'")
            boot_epoch = time.time() - int(cursor.fetchone()["Value"])
        return connection, version, boot_epoch
    except BaseException:
        connection.close()
        raise


def poll(connection, version):
    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM information_schema.PROCESSLIST" if "mariadb" in version.lower()
                       else "SHOW FULL PROCESSLIST")
        return [{key.upper(): value for key, value in row.items()} for row in cursor.fetchall()]


def observation(row):
    sql = query_text(row)
    qid = row.get("QUERY_ID")
    if sql is not None and qid is not None and int(qid) > 0:
        return ("query-id", str(qid)), None
    key = tuple(row.get(k) for k in ("USER", "HOST", "DB", "COMMAND")) + (sql,)
    elapsed = float(row.get("TIME_MS", (row.get("TIME") or 0) * 1000) or 0) / 1000
    return key, elapsed


def json_field(value):
    if isinstance(value, bytes):
        return {"encoding": "base64", "data": base64.b64encode(value).decode("ascii")}
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"Unsupported process field: {type(value).__name__}")


def capture(rows, previous, output, target_ip):
    current, count = {}, 0
    for row in rows:
        pid = int(row["ID"])
        key, elapsed = observation(row)
        old = previous.get(pid)
        duplicate = old and key == old[0] and (elapsed is None or elapsed + 0.001 >= old[1])
        if not duplicate:
            event = {"captured_at_utc": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                     "target_ip": target_ip, "process_id": pid, "user": row.get("USER"),
                     "host": row.get("HOST"), "database": row.get("DB"), "command": row.get("COMMAND"),
                     "elapsed_seconds": row.get("TIME"), "state": row.get("STATE"),
                     "query": query_text(row), "process": row}
            output.write(json.dumps(event, ensure_ascii=True, default=json_field) + "\n")
            output.flush()
            os.fsync(output.fileno())
            logging.info("Captured process_id=%s user=%s host=%s", pid, row.get("USER"), row.get("HOST"))
            count += 1
        current[pid] = key, elapsed
    return current, count


@contextmanager
def single_instance():
    # A small OS lock prevents an accidental second copy duplicating the log.
    with Path(str(QUERY_LOG) + ".lock").open("a+b") as lock:
        if lock.tell() == 0:
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise ValueError("Another watcher is already running from this folder") from exc
        yield


def run(config, check=False):
    DATA.mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s UTC %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(DATA / "watcher.log", encoding="utf-8")], force=True)
    logging.Formatter.converter = time.gmtime
    connection, previous, warned = None, {}, set()
    previous_boot, retry, total, successful = None, 1, 0, 0
    deadline = time.monotonic() + config["max_hours"] * 3600
    heartbeat = time.monotonic()
    logging.info("IP Watch %s: target=%s interval=%ss max_hours=%s log=%s", VERSION,
                 config["target_ip"], config["interval_seconds"], config["max_hours"], QUERY_LOG)
    try:
        with single_instance(), QUERY_LOG.open("a", encoding="utf-8") as output:
            while time.monotonic() < deadline:
                started = time.monotonic()
                try:
                    if connection is None:
                        connection, version, boot = connect(config)
                        if previous_boot is not None and abs(boot - previous_boot) > 5:
                            previous.clear()
                        previous_boot = boot
                        logging.info("Connected to %s; monitoring_connection_id=%s", version, connection.thread_id())
                    rows = matching_rows(poll(connection, version), config, connection.thread_id(), warned)
                    if check:
                        print(f"Connection OK; all-user PROCESS visibility OK; matching connections: {len(rows)}")
                        return 0
                    previous, added = capture(rows, previous, output, config["target_ip"])
                    total, successful, retry = total + added, successful + 1, 1
                    if time.monotonic() >= heartbeat:
                        logging.info("Polling OK: matching_connections=%s total_captured=%s", len(rows), total)
                        heartbeat = time.monotonic() + 60
                    wait = max(0, config["interval_seconds"] - (time.monotonic() - started))
                except pymysql.MySQLError as exc:
                    if connection is not None:
                        connection.close()
                        connection = None
                    code = exc.args[0] if exc.args and isinstance(exc.args[0], int) else "unknown"
                    # Driver text can contain credentials: record only its numeric code.
                    logging.warning("Database error code=%s", code)
                    if check or code in (1044, 1045, 1142, 1227, 1698):
                        logging.error("Check mysql settings and PROCESS permission in SETUP.md")
                        return 2
                    logging.info("Retrying in %ss", retry)
                    wait, retry = retry, min(30, retry * 2)
                time.sleep(min(wait, max(0, deadline - time.monotonic())))
    finally:
        if connection is not None:
            connection.close()
        logging.info("Stopped; captured %s events in this run", total)
    return 0 if successful else 2


def main():
    parser = argparse.ArgumentParser(description="Watch one client IP for up to seven days; stop early with Ctrl+C.")
    parser.add_argument("--config", type=Path, default=ROOT / "config.json")
    parser.add_argument("--check", action="store_true", help="Check settings and visibility without capturing queries")
    parser.add_argument("--version", action="version", version=VERSION)
    args = parser.parse_args()
    try:
        return run(load_config(args.config), args.check)
    except KeyboardInterrupt:
        return 0
    except (ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
