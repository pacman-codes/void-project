#!/usr/bin/env python3
from __future__ import annotations

import ipaddress
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from services.server_registry import get_server_node
from services.subscription_topology import CURRENT_SUBSCRIPTION_SERVER_CODES


SECRETS_PATH = Path(
    os.getenv("SERVER_SECRETS_PATH", "/etc/void/server_secrets.env")
)
TEST_URL = os.getenv("HY2_AUDIT_TEST_URL", "https://api.ipify.org")
CONNECT_TIMEOUT_SECONDS = int(os.getenv("HY2_AUDIT_CONNECT_TIMEOUT", "15"))


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def parse_bool(value: str, default: bool = False) -> bool:
    normalized = value.strip().lower()
    if not normalized:
        return default
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"unsupported boolean value: {value!r}")


def find_hysteria_binary() -> Path | None:
    candidates: list[str] = []

    configured = os.getenv("HYSTERIA_BIN", "").strip()
    if configured:
        candidates.append(configured)

    discovered = shutil.which("hysteria")
    if discovered:
        candidates.append(discovered)

    candidates.extend(
        [
            "/usr/local/bin/hysteria",
            "/usr/bin/hysteria",
            "/opt/hysteria/hysteria",
        ]
    )

    try:
        raw_exec_start = subprocess.check_output(
            ["systemctl", "show", "hysteria-server", "-p", "ExecStart", "--value"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        raw_exec_start = ""

    for match in re.findall(r"(/[A-Za-z0-9_./-]*hysteria[A-Za-z0-9_./-]*)", raw_exec_start):
        candidates.append(match)

    for raw in candidates:
        path = Path(raw)
        if path.is_file() and os.access(path, os.X_OK):
            return path

    return None


def free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for_tcp_port(port: int, process: subprocess.Popen[str]) -> bool:
    deadline = time.monotonic() + CONNECT_TIMEOUT_SECONDS

    while time.monotonic() < deadline:
        if process.poll() is not None:
            return False

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.2)
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                return True

        time.sleep(0.2)

    return False


def sanitize(text: str, secrets: list[str]) -> str:
    result = text
    for secret in secrets:
        if secret:
            result = result.replace(secret, "***hidden***")
    return result


def build_client_config(
    *,
    host: str,
    port: int,
    auth: str,
    sni: str,
    insecure: bool,
    http_port: int,
    obfs_type: str,
    obfs_password: str,
) -> dict[str, Any]:
    config: dict[str, Any] = {
        "server": f"{host}:{port}",
        "auth": auth,
        "tls": {
            "sni": sni,
            "insecure": insecure,
        },
        "http": {
            "listen": f"127.0.0.1:{http_port}",
        },
    }

    if obfs_type:
        config["obfs"] = {
            "type": obfs_type,
            obfs_type: {
                "password": obfs_password,
            },
        }

    return config


def test_endpoint(
    *,
    binary: Path,
    code: str,
    host: str,
    port: int,
    auth: str,
    sni: str,
    insecure: bool,
    obfs_type: str,
    obfs_password: str,
) -> bool:
    http_port = free_local_port()
    config = build_client_config(
        host=host,
        port=port,
        auth=auth,
        sni=sni,
        insecure=insecure,
        http_port=http_port,
        obfs_type=obfs_type,
        obfs_password=obfs_password,
    )

    with tempfile.TemporaryDirectory(prefix=f"void-hy2-audit-{code}-") as temp_dir:
        config_path = Path(temp_dir) / "client.json"
        config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n")
        config_path.chmod(0o600)

        process = subprocess.Popen(
            [str(binary), "client", "-c", str(config_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        try:
            proxy_ready = wait_for_tcp_port(http_port, process)

            if not proxy_ready:
                try:
                    output, _ = process.communicate(timeout=2)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    output, _ = process.communicate(timeout=3)

                print(f"{code}: FAIL — local proxy did not start")
                print(sanitize(output[-4000:], [auth, obfs_password]))
                return False

            curl = subprocess.run(
                [
                    "curl",
                    "--silent",
                    "--show-error",
                    "--fail",
                    "--max-time",
                    str(CONNECT_TIMEOUT_SECONDS),
                    "--proxy",
                    f"http://127.0.0.1:{http_port}",
                    TEST_URL,
                ],
                text=True,
                capture_output=True,
            )

            if curl.returncode != 0:
                print(f"{code}: FAIL — proxy started, request failed")
                print(sanitize((curl.stderr or curl.stdout)[-2000:], [auth, obfs_password]))
                return False

            response = curl.stdout.strip()
            try:
                ipaddress.ip_address(response)
                response_label = response
            except ValueError:
                response_label = f"response={response[:120]!r}"

            print(f"{code}: END-TO-END OK — exit={response_label}")
            return True
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)


def main() -> int:
    print("== HY2 runtime audit (secrets masked) ==")
    print(f"secrets_file={SECRETS_PATH}")
    print(f"test_url={TEST_URL}")

    if not SECRETS_PATH.is_file():
        print("ERROR: server secrets file not found")
        return 1

    values = load_env_file(SECRETS_PATH)
    binary = find_hysteria_binary()

    if binary is None:
        print("ERROR: Hysteria binary not found; set HYSTERIA_BIN=/path/to/hysteria")
        return 1

    print(f"hysteria_binary={binary}")
    version = subprocess.run(
        [str(binary), "version"],
        text=True,
        capture_output=True,
    )
    version_text = (version.stdout or version.stderr).strip().splitlines()
    if version_text:
        print(f"hysteria_version={version_text[0]}")

    failures = 0

    for code in CURRENT_SUBSCRIPTION_SERVER_CODES:
        node = get_server_node(code)
        prefix = node.secret_ref

        auth = values.get(f"{prefix}_HY2_AUTH", "").strip()
        port_raw = values.get(f"{prefix}_HY2_PORT", str(node.public_port)).strip()
        sni = values.get(f"{prefix}_HY2_SNI", node.public_host).strip() or node.public_host
        insecure_raw = values.get(f"{prefix}_HY2_INSECURE", "1").strip()
        obfs_type = values.get(f"{prefix}_HY2_OBFS", "").strip().lower()
        obfs_password = values.get(f"{prefix}_HY2_OBFS_PASSWORD", "").strip()

        try:
            port = int(port_raw)
            insecure = parse_bool(insecure_raw, default=True)
        except Exception as exc:
            print(f"{code}: invalid HY2 settings: {exc}")
            failures += 1
            continue

        try:
            addresses = sorted(
                {
                    item[4][0]
                    for item in socket.getaddrinfo(
                        node.public_host,
                        port,
                        type=socket.SOCK_DGRAM,
                    )
                }
            )
        except Exception as exc:
            addresses = [f"DNS ERROR: {exc}"]

        print()
        print(f"[{code}]")
        print(f"endpoint={node.public_host}:{port}")
        print(f"resolved={addresses}")
        print(f"sni={sni}")
        print(f"insecure={insecure}")
        print(f"auth_present={bool(auth)} auth_length={len(auth)}")
        print(f"obfs={obfs_type or '-'} obfs_password_present={bool(obfs_password)}")

        if not auth:
            print(f"{code}: FAIL — missing {prefix}_HY2_AUTH")
            failures += 1
            continue

        if obfs_type and not obfs_password:
            print(f"{code}: FAIL — obfs enabled but password missing")
            failures += 1
            continue

        if not test_endpoint(
            binary=binary,
            code=code,
            host=node.public_host,
            port=port,
            auth=auth,
            sni=sni,
            insecure=insecure,
            obfs_type=obfs_type,
            obfs_password=obfs_password,
        ):
            failures += 1

    print()
    print(f"HY2_AUDIT_FAILURES={failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
