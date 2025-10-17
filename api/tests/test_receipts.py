from latticedb.merkle import merkle_root

def test_merkle_root_empty():
    assert isinstance(merkle_root([]), str)