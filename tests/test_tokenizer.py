"""ch16 T10：count_tokens + estimate_conversation_tokens 测试。"""

from aixcode.context import tokenizer
from aixcode.context.tokenizer import count_tokens, estimate_conversation_tokens
from aixcode.conversation import ConversationManager


def test_count_tokens_empty_zero():
    assert count_tokens("") == 0


def test_count_tokens_nonempty_positive():
    assert count_tokens("hello world this is a test") > 0


def test_count_tokens_fallback_when_no_encoder(monkeypatch):
    monkeypatch.setattr(tokenizer, "_get_encoder", lambda: None)
    assert count_tokens("a" * 40) == 10  # max(1, 40 // 4)
    assert count_tokens("x") == 1  # max(1, 0)


def test_estimate_conversation_grows(monkeypatch):
    monkeypatch.setattr(tokenizer, "_get_encoder", lambda: None)
    conv = ConversationManager()
    conv.add_user_message("short")
    base = estimate_conversation_tokens(conv)
    assert base > 0
    conv.add_assistant_message("a much longer assistant reply " * 20)
    assert estimate_conversation_tokens(conv) > base
