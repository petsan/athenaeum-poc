import pytest, textwrap
from athenaeum_body.config import Config, ConfigError

def write(tmp_path, text):
    p = tmp_path / "c.yaml"
    p.write_text(textwrap.dedent(text))
    return str(p)

def test_valid_config_loads(tmp_path):
    path = write(tmp_path, """
        memory: {local_dram_gb: 512, working_set_floor_gb: 16}
        ingestion: {disallow_paid_apis: true}
        concurrency: {question_ledger_retention: permanent}
    """)
    cfg = Config.load(path)
    assert cfg.get("memory", "local_dram_gb") == 512

def test_floor_must_be_below_dram(tmp_path):
    path = write(tmp_path, "memory: {local_dram_gb: 512, working_set_floor_gb: 600}")
    with pytest.raises(ConfigError):
        Config.load(path)

def test_paid_apis_invariant_enforced(tmp_path):
    path = write(tmp_path, "ingestion: {disallow_paid_apis: false}")
    with pytest.raises(ConfigError):
        Config.load(path)
