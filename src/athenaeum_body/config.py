"""Config schema + loader/validator (Section 8). Hard invariants enforced here."""
from __future__ import annotations
from dataclasses import dataclass
import yaml


class ConfigError(Exception):
    pass


DEFAULTS = {
    "compute": {"local_cores_min": 1, "local_cores_max": 40},
    "memory": {"local_dram_gb": 512, "working_set_floor_gb": 16},
    "concurrency": {"question_ledger_retention": "permanent"},
    "ingestion": {"disallow_paid_apis": True},
}


@dataclass
class Config:
    raw: dict

    @staticmethod
    def load(path: str) -> "Config":
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        cfg = Config(raw=data)
        cfg.validate()
        return cfg

    def validate(self) -> None:
        mem = self.raw.get("memory", {})
        dram = mem.get("local_dram_gb", DEFAULTS["memory"]["local_dram_gb"])
        floor = mem.get("working_set_floor_gb", DEFAULTS["memory"]["working_set_floor_gb"])
        if floor >= dram:
            raise ConfigError("working_set_floor_gb must be < local_dram_gb")
        ing = self.raw.get("ingestion", {})
        if ing.get("disallow_paid_apis", True) is not True:
            raise ConfigError("disallow_paid_apis is a hard invariant and cannot be disabled")
        ledger = self.raw.get("concurrency", {})
        if ledger.get("question_ledger_retention", "permanent") != "permanent":
            raise ConfigError("question_ledger_retention is a hard invariant: must be 'permanent'")

    def get(self, *path, default=None):
        node = self.raw
        for p in path:
            if not isinstance(node, dict) or p not in node:
                return default
            node = node[p]
        return node
