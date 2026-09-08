from storage.seen_listings import SeenListingsStore


def test_new_store_has_no_seen_ids(tmp_path):
    store = SeenListingsStore(tmp_path / "seen.json")

    assert store.seen_ids() == set()


def test_mark_seen_persists_ids(tmp_path):
    store = SeenListingsStore(tmp_path / "seen.json")

    store.mark_seen([1, 2, 3])

    assert store.seen_ids() == {1, 2, 3}


def test_mark_seen_accumulates_across_calls(tmp_path):
    store = SeenListingsStore(tmp_path / "seen.json")

    store.mark_seen([1, 2])
    store.mark_seen([3])

    assert store.seen_ids() == {1, 2, 3}


def test_persists_across_new_instances(tmp_path):
    path = tmp_path / "seen.json"
    SeenListingsStore(path).mark_seen([42])

    reloaded = SeenListingsStore(path)

    assert 42 in reloaded.seen_ids()
