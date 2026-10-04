from passwords import hash_password, verify_password


def test_hash_round_trip():
    stored = hash_password("correct horse")
    assert stored.startswith("pbkdf2_sha256$")
    assert "correct horse" not in stored
    assert verify_password("correct horse", stored)
    assert not verify_password("wrong horse", stored)
    assert not verify_password("correct horse", "not-a-hash")
