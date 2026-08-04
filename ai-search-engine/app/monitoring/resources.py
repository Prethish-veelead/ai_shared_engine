"""System/container-level resource numbers for the admin Resources page.

Deliberately does NOT report per-bot RAM/CPU - there is no such thing on this
deployment. All bots share one `api` container and one `worker` container
(see docker-compose.yml), so there is no OS-level "this bot used X MB."
Reporting a fabricated per-bot RAM number would be worse than not reporting
one at all - see app/monitoring/activity.py for the honest alternative (a
labeled load proxy).

Reads cgroup files directly first (accurate for THIS container, works with
no extra dependency), falling back to psutil's host-level view when cgroup
files aren't present (e.g. running outside a container during local dev).
Per-container breakdown needs the Docker socket mounted into this container,
which docker-compose.yml does not do - so `containers` is always None here,
`containersAvailable` always False, with a note explaining why. Never raises
just because Docker isn't reachable.

Security: returns only aggregate metrics - no env vars, no file paths beyond
the fixed data-volume path, no process command lines.
"""
import os
import shutil
import time

_CACHE_TTL_SECONDS = 20.0
_cache: dict = {"data": None, "at": 0.0}

# cgroup v2 (modern Docker default) vs v1 paths.
_CGROUP_V2_MEM_CURRENT = "/sys/fs/cgroup/memory.current"
_CGROUP_V2_MEM_MAX = "/sys/fs/cgroup/memory.max"
_CGROUP_V1_MEM_CURRENT = "/sys/fs/cgroup/memory/memory.usage_in_bytes"
_CGROUP_V1_MEM_MAX = "/sys/fs/cgroup/memory/memory.limit_in_bytes"

# cgroup v1's "no limit" sentinel is a huge number (commonly 2^63-ish, minus
# a page size), not a real byte count - treat anything absurdly large as
# "unlimited" and fall back instead of reporting a meaningless multi-exabyte cap.
_V1_UNLIMITED_THRESHOLD = 1 << 62


def _read_int(path: str) -> int | None:
    try:
        with open(path) as f:
            value = f.read().strip()
        if value == "max":
            return None
        return int(value)
    except (OSError, ValueError):
        return None


def _cgroup_memory() -> tuple[int, int] | None:
    used = _read_int(_CGROUP_V2_MEM_CURRENT)
    limit = _read_int(_CGROUP_V2_MEM_MAX)
    if used is not None and limit is not None:
        return used, limit

    used = _read_int(_CGROUP_V1_MEM_CURRENT)
    limit = _read_int(_CGROUP_V1_MEM_MAX)
    if used is not None and limit is not None and limit < _V1_UNLIMITED_THRESHOLD:
        return used, limit

    return None


def _compute_resources() -> dict:
    import psutil

    cgroup_mem = _cgroup_memory()
    if cgroup_mem is not None:
        used_bytes, limit_bytes = cgroup_mem
        source = "cgroup"
    else:
        vm = psutil.virtual_memory()
        used_bytes, limit_bytes = vm.used, vm.total
        source = "psutil"

    mem_pct = round(100 * used_bytes / limit_bytes, 1) if limit_bytes else 0.0
    cpu_pct = psutil.cpu_percent(interval=0.1)

    # The data volume path inside this container - not a host path, and not
    # configurable from the request, so nothing sensitive can leak through it.
    disk_path = "/app" if os.path.isdir("/app") else "/"
    disk = shutil.disk_usage(disk_path)
    disk_pct = round(100 * disk.used / disk.total, 1) if disk.total else 0.0

    process = psutil.Process()
    with process.oneshot():
        rss_bytes = process.memory_info().rss
        process_cpu_pct = process.cpu_percent(interval=0.1)

    return {
        "memory": {"usedBytes": used_bytes, "limitBytes": limit_bytes, "pct": mem_pct},
        "cpu": {"pct": cpu_pct},
        "disk": {"totalBytes": disk.total, "usedBytes": disk.used, "freeBytes": disk.free, "pct": disk_pct},
        "process": {"rssBytes": rss_bytes, "cpuPct": process_cpu_pct},
        "containers": None,
        "containersAvailable": False,
        "source": source,
        "note": "Per-container breakdown needs Docker socket access on the VM - "
                "not mounted in this deployment (see docs/ADMIN_RESOURCES_PAGE.md).",
    }


def get_resources() -> dict:
    now = time.monotonic()
    if _cache["data"] is not None and now - _cache["at"] < _CACHE_TTL_SECONDS:
        return _cache["data"]
    data = _compute_resources()
    _cache["data"] = data
    _cache["at"] = now
    return data
