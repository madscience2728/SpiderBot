"""
llm_brain.py — the real (non-mock) decision-maker. Pattern borrowed from
Ezra's LMToolNode: give the model tools, let it pick one, execute it.

Deliberately the SIMPLEST possible version, per the MVP goal: no system
prompt engineering, no conversation history, no follow-up message after
the tool executes — one user message describing current sensors, one
tool call chosen, one action executed. Build up from here once this loop
is proven end to end.
"""

import json

from spider_brain.config_loader import load_system_prompt
from spider_brain.llm_adapter import LLMAdapter
from spider_brain.tools import GAIT_TOOLS, execute_tool

_adapter = LLMAdapter()
_system_prompt = load_system_prompt()


def decide_and_act(sensors: dict) -> dict:
    """One full LLM-driven cycle: observe (sensors) -> decide (tool call)
    -> act (execute it). Returns what happened, for logging/status."""
    messages = [
        {"role": "system", "content": _system_prompt},
        {
            "role": "user",
            "content": f"Current sensor reading: {sensors}. Choose one action.",
        },
    ]

    _adapter.ensure_ready()
    response = _adapter.complete_with_tools(messages, GAIT_TOOLS)

    if not response.get("tool_calls"):
        return {
            "action": None,
            "reason": "model did not choose a tool",
            "raw_content": response.get("content"),
        }

    # MVP: only act on the first tool call, ignore any additional ones
    tool_call = response["tool_calls"][0]
    function_name = tool_call["function"]["name"]
    try:
        arguments = json.loads(tool_call["function"]["arguments"])
    except (json.JSONDecodeError, KeyError):
        arguments = {}

    result = execute_tool(function_name, arguments)
    return {"tool_chosen": function_name, "execution_result": result}
