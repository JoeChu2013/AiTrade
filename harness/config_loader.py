"""集中加载 harness 配置与股票池。所有阈值的唯一真相来源。"""
from __future__ import annotations

import os
from functools import lru_cache

import yaml

CONFIG_DIR = os.path.join(os.path.dirname(__file__), "config")


@lru_cache(maxsize=1)
def load_config() -> dict:
    path = os.path.join(CONFIG_DIR, "harness_config.yaml")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_pool(filename: str) -> dict:
    path = os.path.join(CONFIG_DIR, filename)
    if not os.path.exists(path):
        return {"pool_name": filename, "stocks": []}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {"stocks": []}


def reload() -> None:
    """配置热更新后调用（仅协调器有权，对应禁止行为 P-12）。"""
    load_config.cache_clear()
