"""
config_loader.py — loads config/config.json, same pattern as Ezra's
load_config(): one small function, called wherever settings are needed.

config/config.json lives at the project root (sibling to spider_brain/,
spider_robot/, scripts/) — same relative layout Ezra uses.
"""

import json
from pathlib import Path


def load_config() -> dict:
    config_path = Path(__file__).parent.parent / "config" / "config.json"
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_system_prompt() -> str:
    prompt_path = Path(__file__).parent.parent / "config" / "system_prompt.md"
    with open(prompt_path, "r", encoding="utf-8") as f:
        return f.read()


def load_seed_conversation() -> list:
    """Few-shot priming turns (see config/seed_conversation.json) -- a short
    synthetic dialogue that establishes the robot role conversationally,
    prepended before the real per-cycle loop starts."""
    seed_path = Path(__file__).parent.parent / "config" / "seed_conversation.json"
    with open(seed_path, "r", encoding="utf-8") as f:
        return json.load(f)
