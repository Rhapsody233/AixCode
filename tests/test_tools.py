import asyncio
import sys

from aixcode.tools.bash import Bash
from aixcode.tools.edit_file import EditFile
from aixcode.tools.glob import Glob
from aixcode.tools.grep import Grep
from aixcode.tools.read_file import ReadFile
from aixcode.tools.write_file import WriteFile


def _run(tool, **kwargs):
    params = tool.params_model(**kwargs)
    return asyncio.run(tool.execute(params))


# --- ReadFile ---------------------------------------------------------------

def test_read_file_numbers_lines_1_based(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("first\nsecond\nthird\n", encoding="utf-8")

    result = _run(ReadFile(), file_path=str(p))

    assert result.is_error is False
    assert result.output == "1\tfirst\n2\tsecond\n3\tthird"


def test_read_file_offset_and_limit(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("l1\nl2\nl3\nl4\nl5\n", encoding="utf-8")

    result = _run(ReadFile(), file_path=str(p), offset=1, limit=2)

    assert result.output == "2\tl2\n3\tl3"


def test_read_file_missing_is_error(tmp_path):
    result = _run(ReadFile(), file_path=str(tmp_path / "nope.txt"))
    assert result.is_error is True


def test_read_file_directory_is_error(tmp_path):
    result = _run(ReadFile(), file_path=str(tmp_path))
    assert result.is_error is True


def test_read_file_metadata():
    tool = ReadFile()
    assert tool.name == "ReadFile"
    assert tool.category == "read"
    assert tool.is_concurrency_safe is True


# --- WriteFile --------------------------------------------------------------

def test_write_file_creates_parent_dirs(tmp_path):
    target = tmp_path / "sub" / "deep" / "out.txt"

    result = _run(WriteFile(), file_path=str(target), content="hello")

    assert result.is_error is False
    assert "Successfully wrote to" in result.output
    assert target.read_text(encoding="utf-8") == "hello"


def test_write_file_category():
    assert WriteFile().category == "write"


# --- EditFile ---------------------------------------------------------------

def test_edit_file_unique_match_replaces(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("alpha beta gamma", encoding="utf-8")

    result = _run(EditFile(), file_path=str(p), old_string="beta", new_string="BETA")

    assert result.is_error is False
    assert p.read_text(encoding="utf-8") == "alpha BETA gamma"


def test_edit_file_not_found_is_error(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("alpha", encoding="utf-8")

    result = _run(EditFile(), file_path=str(p), old_string="zzz", new_string="x")

    assert result.is_error is True
    assert "not found" in result.output


def test_edit_file_multiple_matches_is_error(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("x x x", encoding="utf-8")

    result = _run(EditFile(), file_path=str(p), old_string="x", new_string="y")

    assert result.is_error is True
    assert "must be unique" in result.output
    # 未匹配唯一时不应改动文件
    assert p.read_text(encoding="utf-8") == "x x x"


# --- Bash -------------------------------------------------------------------

def test_bash_echo_captures_stdout():
    result = _run(Bash(), command="echo hello")
    assert result.is_error is False
    assert "STDOUT:" in result.output
    assert "hello" in result.output


def test_bash_nonzero_exit_is_error():
    result = _run(Bash(), command="exit 1")
    assert result.is_error is True


def test_bash_timeout_is_error():
    cmd = f'{sys.executable} -c "import time; time.sleep(5)"'
    result = _run(Bash(), command=cmd, timeout=1)
    assert result.is_error is True
    assert "timed out" in result.output


def test_bash_metadata():
    from aixcode.tools.bash import MAX_TIMEOUT

    assert Bash().category == "command"
    assert MAX_TIMEOUT == 600


# --- Glob -------------------------------------------------------------------

def test_glob_finds_files_sorted(tmp_path):
    (tmp_path / "b.txt").write_text("", encoding="utf-8")
    (tmp_path / "a.txt").write_text("", encoding="utf-8")

    result = _run(Glob(), pattern="*.txt", path=str(tmp_path))

    assert result.output == "a.txt\nb.txt"


def test_glob_no_match(tmp_path):
    result = _run(Glob(), pattern="*.nope", path=str(tmp_path))
    assert result.output == "No files matched the pattern."


def test_glob_skips_skip_dirs(tmp_path):
    (tmp_path / "real.py").write_text("", encoding="utf-8")
    cache = tmp_path / "__pycache__"
    cache.mkdir()
    (cache / "x.py").write_text("", encoding="utf-8")

    result = _run(Glob(), pattern="**/*.py", path=str(tmp_path))

    assert "real.py" in result.output
    assert "x.py" not in result.output


def test_glob_concurrency_safe():
    assert Glob().is_concurrency_safe is True


# --- Grep -------------------------------------------------------------------

def test_grep_finds_matches(tmp_path):
    (tmp_path / "a.txt").write_text("foo\nneedle here\nbar\n", encoding="utf-8")

    result = _run(Grep(), pattern="needle", path=str(tmp_path))

    assert "a.txt:2:needle here" in result.output


def test_grep_no_match(tmp_path):
    (tmp_path / "a.txt").write_text("foo\n", encoding="utf-8")
    result = _run(Grep(), pattern="zzz", path=str(tmp_path))
    assert result.output == "No matches found."


def test_grep_invalid_regex_is_error(tmp_path):
    result = _run(Grep(), pattern="(unclosed", path=str(tmp_path))
    assert result.is_error is True


def test_grep_include_filter(tmp_path):
    (tmp_path / "a.py").write_text("needle\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("needle\n", encoding="utf-8")

    result = _run(Grep(), pattern="needle", path=str(tmp_path), include="*.py")

    assert "a.py:1:needle" in result.output
    assert "b.txt" not in result.output
