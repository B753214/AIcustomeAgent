"""Memory-M2-4：会话消息落库前 DataPolicy 脱敏。"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.harness.policies import DataPolicy
from app.services.session_service import save_message


def test_data_policy_masks_sk_and_phone():
    d = DataPolicy()
    text = "key=sk-abcdefghijklmnop phone=13812345678"
    out = d.mask_str(text)
    assert "sk-abcdefghijklmnop" not in out
    assert "13812345678" not in out
    assert "sk-" in out or "*" in out
    assert "*" in out


@pytest.mark.asyncio
async def test_save_message_redacts_content_and_metadata():
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    caller_meta = {
        "sources": ["doc?token=sk-abcdefghijklmnop", "ok#1"],
    }

    msg = await save_message(
        "s1",
        "assistant",
        "联系 13900001111 或 sk-ABCDEFGHIJKLMN12",
        db,
        metadata=caller_meta,
    )

    assert "13900001111" not in msg.content
    assert "sk-ABCDEFGHIJKLMN12" not in msg.content
    assert "*" in msg.content
    # 调用方 dict 未被原地污染
    assert caller_meta["sources"][0] == "doc?token=sk-abcdefghijklmnop"
    assert msg.message_metadata is not None
    joined = " ".join(msg.message_metadata.get("sources") or [])
    assert "sk-abcdefghijklmnop" not in joined
    assert "ok#1" in joined
