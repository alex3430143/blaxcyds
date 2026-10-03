import time

from blaxcy.memory import Memory
from blaxcy.models import TrustLevel


def test_add_query_and_count(tmp_memory: Memory):
    tmp_memory.add("opened gedit successfully", kind="lesson", tags=["editor"])
    tmp_memory.add("firefox crashed on launch", kind="experience")
    assert tmp_memory.count() == 2
    assert len(tmp_memory.query(text="gedit")) == 1
    assert len(tmp_memory.query(tag="editor")) == 1
    assert len(tmp_memory.recent_lessons()) == 1


def test_trusted_only_filter(tmp_memory: Memory):
    tmp_memory.add("from a webpage", trust=TrustLevel.UNTRUSTED)
    tmp_memory.add("from the user", trust=TrustLevel.TRUSTED)
    assert len(tmp_memory.query(trusted_only=True)) == 1


def test_secrets_are_redacted_before_storage(tmp_memory: Memory):
    tmp_memory.add("api_key=sk-abcdefghijklmnop and password=hunter2"
                   " and token: ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345")
    record = tmp_memory.query(limit=1)[0]
    assert "hunter2" not in record.content
    assert "sk-abcdefghijklmnop" not in record.content
    assert "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345" not in record.content


def test_confidence_clamped(tmp_memory: Memory):
    low = tmp_memory.add("low", confidence=-5)
    high = tmp_memory.add("high", confidence=5)
    assert low.confidence == 0.0
    assert high.confidence == 1.0


def test_expiry_filtering(tmp_memory: Memory):
    tmp_memory.add("transient", expires_at=time.time() - 1)
    assert tmp_memory.query() == []
    assert len(tmp_memory.query(include_expired=True)) == 1


def test_forget(tmp_memory: Memory):
    rec = tmp_memory.add("forget me")
    assert tmp_memory.forget(rec.record_id)
    assert tmp_memory.count() == 0
