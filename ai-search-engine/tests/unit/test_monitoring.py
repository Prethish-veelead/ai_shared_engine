"""Pure-logic unit tests for the admin Resources page's backend
(app/monitoring/) - no real Postgres/Qdrant needed for these. Covers the
vector-size estimate math, the cgroup reader's graceful handling of missing/
malformed files, the activity %share math, and - per this feature's explicit
acceptance criterion - that GET /admin/resources' response never contains
anything secret-shaped (env vars, arbitrary file paths, process command
lines).

Stateful behavior (real pg_total_relation_size against a real Postgres list
table, real Qdrant index_stats, the actual cgroup/psutil numbers inside the
container) was verified live, consistent with how the rest of this repo's
work has been verified throughout.
"""
import app.monitoring.resources as resources_module
from app.monitoring.activity import _share
from app.monitoring.resources import _cgroup_memory, _read_int, get_resources
from app.monitoring.storage import _estimate_vector_bytes


# ---- storage.py: vector size estimate ----

def test_estimate_vector_bytes_zero_points_is_zero():
    assert _estimate_vector_bytes(0, 768) == 0


def test_estimate_vector_bytes_scales_with_points_and_dimension():
    small = _estimate_vector_bytes(100, 768)
    large = _estimate_vector_bytes(200, 768)
    assert large == 2 * small  # linear in point count for a fixed dimension

    dim_768 = _estimate_vector_bytes(100, 768)
    dim_1536 = _estimate_vector_bytes(100, 1536)
    assert dim_1536 > dim_768  # a larger embedding dimension costs more bytes/point


def test_estimate_vector_bytes_includes_per_point_overhead():
    # Even a hypothetical zero-dimension vector should cost > 0 bytes/point -
    # the fixed per-point overhead allowance must never be dropped to 0.
    assert _estimate_vector_bytes(10, 0) > 0


# ---- resources.py: cgroup reader ----

def test_read_int_missing_file_returns_none():
    assert _read_int("/no/such/path/on/this/machine") is None


def test_read_int_max_sentinel_returns_none(tmp_path):
    f = tmp_path / "memory.max"
    f.write_text("max")
    assert _read_int(str(f)) is None


def test_read_int_parses_real_value(tmp_path):
    f = tmp_path / "memory.current"
    f.write_text("12345\n")
    assert _read_int(str(f)) == 12345


def test_cgroup_memory_returns_none_when_no_cgroup_files_present(monkeypatch):
    # Simulate running somewhere with no cgroup filesystem at all (e.g. bare
    # host, not inside a Linux container) - must degrade to None, not raise,
    # so get_resources() can fall back to psutil.
    monkeypatch.setattr(resources_module, "_read_int", lambda path: None)
    assert _cgroup_memory() is None


def test_get_resources_shape_and_no_secrets():
    data = get_resources()

    # Required top-level shape.
    assert set(data.keys()) == {
        "memory", "cpu", "disk", "process", "containers",
        "containersAvailable", "source", "note",
    }
    assert data["source"] in ("cgroup", "psutil")
    assert isinstance(data["containersAvailable"], bool)
    if not data["containersAvailable"]:
        assert data["containers"] is None

    # Security: never leak env vars, secrets, or arbitrary host paths/command
    # lines - only aggregate numeric metrics and a couple of fixed labels.
    serialized = str(data)
    for forbidden in ("os.environ", "AZURE_OPENAI", "API_KEY", "PASSWORD", "SECRET", "sys.argv"):
        assert forbidden not in serialized
    # Every leaf value is either a number, a bool, None, or one of the two
    # fixed descriptive strings (source/note) - no unexpected string blobs
    # that could carry a path or command line.
    for section in ("memory", "cpu", "disk", "process"):
        for value in data[section].values():
            assert isinstance(value, (int, float))


# ---- activity.py: %share math ----

def test_share_zero_total_is_zero_not_a_crash():
    assert _share(5, 0) == 0.0


def test_share_computes_percentage():
    assert _share(25, 100) == 25.0


def test_share_rounds_to_one_decimal():
    assert _share(1, 3) == 33.3
