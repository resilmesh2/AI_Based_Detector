# utils.py
from __future__ import annotations

import json
import logging
import os
import socket
import subprocess
import time
from dataclasses import dataclass
from typing import Optional, Any, Dict


# ---------------------------
# Logging
# ---------------------------
def setup_logging(verbosity: int = 0) -> None:
    """Configure root logger once."""
    level = logging.DEBUG if verbosity > 0 else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )


# ---------------------------
# Docker helpers
# ---------------------------
@dataclass
class ContainerInfo:
    id: str
    ip: str


def _run(cmd: list[str]) -> str:
    """Run a shell command and return stdout (stripped). Raise on failure."""
    return subprocess.run(
        cmd, capture_output=True, text=True, check=True
    ).stdout.strip()


def get_container_id_by_name(name: str) -> Optional[str]:
    """
    Return container ID for a fuzzy name match (`docker ps --filter name=`),
    or None if not found.
    """
    try:
        out = _run(["docker", "ps", "-a", "--filter", f"name={name}", "--format", "{{.ID}}"])
        return out or None
    except subprocess.CalledProcessError as e:
        logging.debug("docker ps failed: %s", e)
        return None


def get_container_ip(container_id: str) -> Optional[str]:
    """Return container IP (bridge) from docker inspect, or None on failure."""
    try:
        out = _run([
            "docker", "inspect", "-f",
            "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}",
            container_id,
        ])
        return out or None
    except subprocess.CalledProcessError as e:
        logging.debug("docker inspect failed: %s", e)
        return None


def is_container_running(container_id: str) -> bool:
    """True if container is running."""
    try:
        out = _run(["docker", "inspect", "-f", "{{.State.Running}}", container_id])
        return out.lower() == "true"
    except subprocess.CalledProcessError:
        return False


def resolve_container_ip(name: str) -> Optional[ContainerInfo]:
    """
    Best-effort lookup: find container by name, ensure it's running,
    and return ContainerInfo with bridge IP.
    """
    log = logging.getLogger("utils.resolve_container_ip")
    cid = get_container_id_by_name(name)
    if not cid:
        log.error("No container found with name filter %r.", name)
        return None

    if not is_container_running(cid):
        log.error("Container %s exists but is not running.", cid)
        return None

    ip = get_container_ip(cid)
    if not ip:
        log.error("Could not discover IP for container %s.", cid)
        return None

    log.debug("Resolved container %s to IP %s", cid, ip)
    return ContainerInfo(id=cid, ip=ip)


# ---------------------------
# TCP helpers
# ---------------------------
def connect_with_retry(
    host: str,
    port: int,
    timeout_sec: float = 5.0,
    retry_delay_sec: float = 3.0,
    max_retries: int = 0,
    tcp_nodelay: bool = True,
) -> socket.socket:
    """
    Connect to TCP with retries.
    - max_retries == 0  -> retry forever
    - max_retries  > 0  -> retry that many times
    """
    log = logging.getLogger("utils.connect_with_retry")
    attempt = 0
    while True:
        attempt += 1
        try:
            log.info("Connecting to %s:%s (attempt %d)...", host, port, attempt)
            s = socket.create_connection((host, port), timeout=timeout_sec)
            if tcp_nodelay:
                s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            log.info("Connection established.")
            return s
        except OSError as e:
            log.warning("Connection failed: %s", e)
            if max_retries and attempt >= max_retries:
                raise
            time.sleep(retry_delay_sec)


def send_jsonl(sock: socket.socket, payload: object) -> None:
    """Send one JSON line (utf-8)."""
    data = json.dumps(payload, separators=(",", ":")) + "\n"
    sock.sendall(data.encode("utf-8"))


# ---------------------------
# Convenience: env parsing
# ---------------------------
def env_str(name: str, default: Optional[str] = None) -> Optional[str]:
    v = os.getenv(name, default if default is not None else None)
    return v


def env_int(name: str, default: int) -> int:
    v = os.getenv(name)
    try:
        return int(v) if v is not None else default
    except ValueError:
        return default

def flow_to_dict(flow: Any):
    """
    Extract public, non-callable attributes of an NFStream flow into a dict.
    Lists are stringified; unsupported types raise a ValueError which we catch higher.
    """
    out: Dict[str, Any] = {}
    for attr in dir(flow):
        if attr.startswith("_"):
            continue
        val = getattr(flow, attr, None)
        if callable(val):
            continue
        if isinstance(val, (str, int, float, bool)) or val is None:
            out[attr] = val
        elif isinstance(val, list):
            out[attr] = str(val)
        else:
            # Skip exotic objects (datetime, custom structs) to keep payload safe
            continue
    return out