import blake3 as _blake3

from adalog.core.ids import blake3_bytes, blake3_file, new_session_id


def test_ulids_sortable_by_time(seq_bytes):
    a = new_session_id(time_ms=1000, rand=seq_bytes)
    b = new_session_id(time_ms=2000, rand=seq_bytes)
    c = new_session_id(time_ms=3000, rand=seq_bytes)
    assert a < b < c
    assert len(a) == 26


def test_same_time_shares_prefix_differs_in_tail():
    a = new_session_id(time_ms=5000, rand=lambda n: b"\x01" * n)
    b = new_session_id(time_ms=5000, rand=lambda n: b"\x02" * n)
    assert a[:10] == b[:10]  # time prefix (48 bits ~ 10 crockford chars)
    assert a != b


def test_salt_changes_tail_not_order():
    unsalted = new_session_id(time_ms=5000, rand=lambda n: b"\x07" * n)
    salted = new_session_id("host-A", time_ms=5000, rand=lambda n: b"\x07" * n)
    assert unsalted[:10] == salted[:10]
    assert unsalted != salted


def test_blake3_matches_library():
    assert blake3_bytes(b"abc") == "b3:" + _blake3.blake3(b"abc").hexdigest()


def test_blake3_file_roundtrip(tmp_path):
    p = tmp_path / "x.bin"
    p.write_bytes(b"hello world" * 1000)
    assert blake3_file(p) == blake3_bytes(b"hello world" * 1000)
