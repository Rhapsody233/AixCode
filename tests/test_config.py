import pytest

from aixcode.config import ProviderConfig, load_config


def test_load_config_reads_four_fields(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        "protocol: openai\n"
        "model: deepseek-reasoner\n"
        "base_url: https://api.deepseek.com\n"
        "api_key: sk-test\n",
        encoding="utf-8",
    )

    config = load_config(str(cfg_file))

    assert isinstance(config, ProviderConfig)
    assert config.protocol == "openai"
    assert config.model == "deepseek-reasoner"
    assert config.base_url == "https://api.deepseek.com"
    assert config.api_key == "sk-test"


def test_load_config_missing_file_raises_clear_error(tmp_path):
    missing = tmp_path / "nope.yaml"

    with pytest.raises(FileNotFoundError) as exc:
        load_config(str(missing))

    assert "config" in str(exc.value).lower()


def test_load_config_missing_field_raises_clear_error(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("protocol: openai\nmodel: deepseek-chat\n", encoding="utf-8")

    with pytest.raises(ValueError) as exc:
        load_config(str(cfg_file))

    assert "base_url" in str(exc.value)
