"""Token 预估（ch16）：tiktoken（cl100k_base 近似 Deepseek）+ 字符回退。

仅用于状态栏显示与首轮发送前（last_input_tokens=0 的盲区）；压缩判定仍用 API 真实数。
tiktoken 是可选依赖——未安装时优雅回退到 len//4 启发式。
"""

from __future__ import annotations

_ENCODER = None
_ENCODER_TRIED = False


def _get_encoder():
    """惰性取 tiktoken 编码器；未安装/异常返回 None（模块级缓存一次）。"""
    global _ENCODER, _ENCODER_TRIED
    if _ENCODER_TRIED:
        return _ENCODER
    _ENCODER_TRIED = True
    try:
        import tiktoken

        _ENCODER = tiktoken.get_encoding("cl100k_base")
    except Exception:  # noqa: BLE001
        _ENCODER = None
    return _ENCODER


def count_tokens(text: str, model: str = "") -> int:
    """优先用 tiktoken 计数；不可用时回退 max(1, len//4)。空串返 0。"""
    if not text:
        return 0
    enc = _get_encoder()
    if enc is not None:
        try:
            return len(enc.encode(text))
        except Exception:  # noqa: BLE001
            pass
    return max(1, len(text) // 4)


def estimate_conversation_tokens(conversation) -> int:
    """对 history 各消息正文求和（含每条固定开销），作为发送前预估。"""
    total = 0
    for m in conversation.history:
        total += count_tokens(m.content or "") + 4
    return total
