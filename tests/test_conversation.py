from aixcode.conversation import ConversationManager, Message


def test_add_and_serialize_preserves_order_and_roles():
    conv = ConversationManager()
    conv.add_user_message("我叫张三")
    conv.add_assistant_message("你好，张三")
    conv.add_user_message("我叫什么")

    serialized = conv.serialize()

    assert serialized == [
        {"role": "user", "content": "我叫张三"},
        {"role": "assistant", "content": "你好，张三"},
        {"role": "user", "content": "我叫什么"},
    ]


def test_get_messages_returns_message_objects_as_copy():
    conv = ConversationManager()
    conv.add_user_message("hi")

    messages = conv.get_messages()

    assert messages == [Message(role="user", content="hi")]
    messages.append(Message(role="user", content="injected"))
    assert len(conv.get_messages()) == 1  # 浅拷贝，外部 append 不影响内部


def test_tool_call_roundtrip_serializes_to_chat_completions():
    tool_calls = [
        {
            "id": "call_1",
            "type": "function",
            "function": {"name": "ReadFile", "arguments": '{"file_path": "a.txt"}'},
        }
    ]
    conv = ConversationManager()
    conv.add_user_message("读一下 a.txt")
    conv.add_assistant_message("", tool_calls=tool_calls)
    conv.add_tool_result("call_1", "1\thello")
    conv.add_assistant_message("文件第一行是 hello")

    assert conv.serialize() == [
        {"role": "user", "content": "读一下 a.txt"},
        {"role": "assistant", "content": "", "tool_calls": tool_calls},
        {"role": "tool", "tool_call_id": "call_1", "content": "1\thello"},
        {"role": "assistant", "content": "文件第一行是 hello"},
    ]


def test_inject_environment_is_idempotent_head_insert():
    conv = ConversationManager()
    conv.add_user_message("hi")
    conv.inject_environment("# 环境信息\ncwd: /x")
    conv.inject_environment("# 环境信息\ncwd: /x")  # 第二次应被忽略

    msgs = conv.serialize()
    assert msgs[0]["content"] == "# 环境信息\ncwd: /x"  # 头插
    assert sum("环境信息" in m["content"] for m in msgs) == 1  # 只一条


def test_add_system_reminder_wraps_in_tag():
    conv = ConversationManager()
    conv.add_user_message("hi")
    conv.add_system_reminder("计划模式仍生效")

    last = conv.serialize()[-1]
    assert last["role"] == "user"
    assert last["content"] == "<system-reminder>\n计划模式仍生效\n</system-reminder>"


# --- ch09: 长期记忆注入 -----------------------------------------------------

def test_inject_ltm_after_env():
    conv = ConversationManager()
    conv.add_user_message("hi")
    conv.inject_environment("# 环境信息")
    conv.inject_long_term_memory("项目指令内容", "记忆内容")
    contents = [m.content for m in conv.history]
    # env 在最前，其后是项目指令、自动记忆、assistant 占位，再到 user
    assert contents[0] == "# 环境信息"
    assert "## 项目指令" in contents[1] and "项目指令内容" in contents[1]
    assert "## 自动记忆" in contents[2] and "记忆内容" in contents[2]
    assert conv.history[3].role == "assistant"
    assert conv.history[4].content == "hi"
    assert conv.ltm_injected is True


def test_inject_ltm_idempotent():
    conv = ConversationManager()
    conv.add_user_message("hi")
    conv.inject_long_term_memory("指令", "记忆")
    conv.inject_long_term_memory("指令", "记忆")
    assert sum("## 项目指令" in m.content for m in conv.history) == 1


def test_inject_ltm_instructions_only():
    conv = ConversationManager()
    conv.add_user_message("hi")
    conv.inject_long_term_memory("仅指令", "")
    assert any("## 项目指令" in m.content for m in conv.history)
    assert not any("## 自动记忆" in m.content for m in conv.history)
    assert conv.ltm_injected is True


def test_inject_ltm_memories_only():
    conv = ConversationManager()
    conv.add_user_message("hi")
    conv.inject_long_term_memory("", "仅记忆")
    assert any("## 自动记忆" in m.content for m in conv.history)
    assert conv.ltm_injected is True


def test_inject_ltm_nothing():
    conv = ConversationManager()
    conv.add_user_message("hi")
    conv.inject_long_term_memory("", "")
    assert len(conv.history) == 1
    assert conv.ltm_injected is False


def test_replace_history_resets_injection_flags():
    conv = ConversationManager()
    conv.add_user_message("hi")
    conv.inject_environment("env")
    conv.inject_long_term_memory("指令", "记忆")
    conv.replace_history([Message(role="user", content="新历史")])
    assert conv.env_injected is False
    assert conv.ltm_injected is False
