import json
import threading

import pytest

from gametrans.store import Store


def _make_store(tmp_path, max_entries=8000):
    return Store(
        overrides_path=tmp_path / "overrides.json",
        glossary_path=tmp_path / "glossary.json",
        cache_path=tmp_path / "translation_cache.json",
        max_entries=max_entries,
    )


def test_lookup_priority_override_beats_everything(tmp_path):
    store = _make_store(tmp_path)
    store.put("Hello", "สวัสดี (tier1)", tier=1, final=False)
    store.put("Hello", "สวัสดี (tier2 final)", tier=2, final=True)
    store.set_override("Hello", "สวัสดี (override)")

    entry = store.lookup("Hello")
    assert entry.thai == "สวัสดี (override)"


def test_final_cache_beats_non_final(tmp_path):
    store = _make_store(tmp_path)
    store.put("Hi", "หวัดดี (tier1)", tier=1, final=False)
    store.put("Hi", "หวัดดี (tier2)", tier=2, final=True)

    entry = store.lookup("Hi")
    assert entry.thai == "หวัดดี (tier2)"
    assert entry.final is True


def test_final_is_never_overwritten_by_lower_tier(tmp_path):
    store = _make_store(tmp_path)
    store.put("Hi", "final answer", tier=2, final=True)
    store.put("Hi", "stale tier1 retry", tier=1, final=False)

    entry = store.lookup("Hi")
    assert entry.thai == "final answer"
    assert entry.final is True


def test_final_can_be_overwritten_by_another_final(tmp_path):
    store = _make_store(tmp_path)
    store.put("Hi", "first final", tier=2, final=True)
    store.put("Hi", "corrected final", tier=2, final=True)

    entry = store.lookup("Hi")
    assert entry.thai == "corrected final"


def test_lookup_miss_returns_none(tmp_path):
    store = _make_store(tmp_path)
    assert store.lookup("nope") is None


def test_lru_evicts_oldest(tmp_path):
    store = _make_store(tmp_path, max_entries=2)
    store.put("a", "A", tier=1, final=False)
    store.put("b", "B", tier=1, final=False)
    store.put("c", "C", tier=1, final=False)  # evicts "a"

    assert store.lookup("a") is None
    assert store.lookup("b") is not None
    assert store.lookup("c") is not None


def test_save_persists_only_final_entries(tmp_path):
    store = _make_store(tmp_path)
    store.put("final-one", "final text", tier=2, final=True)
    store.put("non-final-one", "temp text", tier=1, final=False)
    store.save()

    data = json.loads((tmp_path / "translation_cache.json").read_text(encoding="utf-8"))
    assert "final-one" in data["entries"]
    assert "non-final-one" not in data["entries"]


def test_atomic_write_does_not_corrupt_on_reload(tmp_path):
    store = _make_store(tmp_path)
    store.set_override("term", "value")
    store.save()

    reloaded = _make_store(tmp_path)
    reloaded.load()
    assert reloaded.get_overrides() == {"term": "value"}


def test_corrupt_file_falls_back_to_backup(tmp_path):
    store = _make_store(tmp_path)
    store.set_override("term", "value")
    store.save()
    store.set_override("term2", "value2")
    store.save()  # now .bak holds the first version (term only)

    # Corrupt the live file; .bak should still be readable
    (tmp_path / "overrides.json").write_text("{ corrupt", encoding="utf-8")

    reloaded = _make_store(tmp_path)
    reloaded.load()
    assert reloaded.get_overrides() == {"term": "value"}


def test_missing_files_load_empty_without_crash(tmp_path):
    store = _make_store(tmp_path)
    store.load()  # no files exist yet
    assert store.get_overrides() == {}
    assert store.get_glossary() == {}
    assert store.lookup("anything") is None


def test_clear_cache_does_not_touch_overrides_or_glossary(tmp_path):
    store = _make_store(tmp_path)
    store.set_override("term", "value")
    store.set_glossary_term("Sword", "ดาบ")
    store.put("cached", "cached-thai", tier=1, final=False)

    store.clear_cache()

    assert store.lookup("cached") is None
    assert store.get_overrides() == {"term": "value"}
    assert store.get_glossary() == {"Sword": "ดาบ"}


def test_thread_safety_concurrent_puts(tmp_path):
    store = _make_store(tmp_path, max_entries=10000)

    def worker(n):
        for i in range(200):
            store.put(f"key-{n}-{i}", f"val-{n}-{i}", tier=1, final=False)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert store.lookup("key-0-0") is not None
    assert store.lookup("key-7-199") is not None
