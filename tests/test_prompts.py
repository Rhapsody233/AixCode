from aixcode.prompts import (
    PromptBuilder,
    PromptSection,
    build_environment_context,
    build_plan_mode_reminder,
    build_system_prompt,
    load_project_instructions,
)


def test_build_orders_by_priority():
    out = (
        PromptBuilder()
        .add(PromptSection("b", 50, "BBB"))
        .add(PromptSection("a", 10, "AAA"))
        .build()
    )
    assert out == "AAA\n\nBBB"


def test_build_skips_empty_sections():
    out = (
        PromptBuilder()
        .add(PromptSection("a", 10, "AAA"))
        .add(PromptSection("blank", 20, "   "))
        .add(PromptSection("c", 30, "CCC"))
        .build()
    )
    assert out == "AAA\n\nCCC"


def test_add_returns_self_for_chaining():
    builder = PromptBuilder()
    assert builder.add(PromptSection("a", 0, "x")) is builder


# --- build_system_prompt ----------------------------------------------------

def test_system_prompt_has_identity_and_no_plan_text():
    out = build_system_prompt()
    assert "AixCode" in out
    assert "file_path:line_number" in out
    assert "计划模式" not in out  # Plan 文案不进系统提示


def test_system_prompt_includes_custom_instructions():
    out = build_system_prompt(custom_instructions="项目规则：一律用中文回复")
    assert "一律用中文回复" in out


def test_system_prompt_lists_deferred_tools():
    out = build_system_prompt(deferred_tools=["ToolSearch", "AskUserQuestion"])
    assert "ToolSearch" in out and "AskUserQuestion" in out


# --- AIXCODE.md -------------------------------------------------------------

def test_load_project_instructions_reads_file(tmp_path):
    (tmp_path / "AIXCODE.md").write_text("用蛇形命名", encoding="utf-8")
    assert load_project_instructions(str(tmp_path)) == "用蛇形命名"


def test_load_project_instructions_missing_returns_empty(tmp_path):
    assert load_project_instructions(str(tmp_path)) == ""


# --- environment ------------------------------------------------------------

def test_environment_context_has_cwd_os_time(tmp_path):
    out = build_environment_context(str(tmp_path))
    assert str(tmp_path) in out
    assert "操作系统" in out or "Operating system" in out
    assert "时间" in out or "time" in out.lower()


# --- plan reminder cadence --------------------------------------------------

def test_plan_reminder_full_on_first_iteration():
    full = build_plan_mode_reminder(1)
    assert "计划模式" in full
    assert "只读" in full


def test_plan_reminder_sparse_on_intermediate_iteration():
    full = build_plan_mode_reminder(1)
    sparse = build_plan_mode_reminder(8)
    assert "计划模式" in sparse
    assert len(sparse) < len(full)


def test_plan_reminder_full_again_on_interval():
    # 每隔 5 轮再发完整版：iteration 6 应与 iteration 1 一样是完整版
    assert build_plan_mode_reminder(6) == build_plan_mode_reminder(1)
