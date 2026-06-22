"""prompt_toolkit 补全器：输入 `/` 命令名时弹候选。"""

from __future__ import annotations

from prompt_toolkit.completion import Completer, Completion

from aixcode.commands.parser import complete
from aixcode.commands.registry import CommandRegistry


class SlashCommandCompleter(Completer):
    """仅当当前行以 `/` 开头且尚未输入空格（还在打命令名）时补全。"""

    def __init__(self, registry: CommandRegistry) -> None:
        self.registry = registry

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if not text.startswith("/") or " " in text:
            return
        for name in complete(self.registry, text):
            yield Completion(name, start_position=-len(text))
