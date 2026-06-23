"""ch16 T11：状态栏 token 预估（last_input_tokens==0 时回退）测试。"""

import io

from rich.console import Console

from aixcode.app import AixCodeApp
from aixcode.conversation import ConversationManager
from aixcode.permissions import PermissionMode


class _MiniAgent:
    def __init__(self):
        self.permission_mode = PermissionMode.DEFAULT
        self.memory_manager = None

        class _Reg:
            def list_tools(self):
                return []

        self.registry = _Reg()

    def set_permission_mode(self, mode):
        self.permission_mode = mode


def _app(conversation):
    app = AixCodeApp(_MiniAgent(), conversation, model="deepseek-chat")
    app.console = Console(file=io.StringIO(), record=True, width=120)
    return app


def test_get_token_count_estimates_when_zero():
    conv = ConversationManager()
    conv.add_user_message("some content to estimate tokens from")
    app = _app(conv)
    assert conv.last_input_tokens == 0
    assert app.get_token_count() > 0  # 来自预估


def test_get_token_count_prefers_real():
    conv = ConversationManager()
    conv.add_user_message("x")
    conv.last_input_tokens = 123
    app = _app(conv)
    assert app.get_token_count() == 123
