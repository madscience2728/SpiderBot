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


def decide_and_act(sensors: dict, image_base64: str = None) -> dict:
    """One full LLM-driven cycle: observe (sensors + camera frame) ->
    decide (tool call) -> act (execute it). Returns what happened, for
    logging/status.

    image_base64 is optional so this still works with the old sensors-only
    flow (or a test harness with no camera) -- when provided, it's sent as
    an image_url content part alongside the text, per llama.cpp's
    OpenAI-compatible vision format. Note: Ezra's project (where this
    adapter pattern comes from) never actually implemented image input
    despite having mmproj configured -- there was no reference code to
    mirror here, so this part is new, not ported.
    """
    print(f"\n[llm_brain] Sensors: {sensors}")

    user_text = f"Current sensor reading: {sensors}. Choose one action."

    if image_base64:
        user_content = [
            {"type": "text", "text": user_text},
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"},
            },
        ]
    else:
        user_content = user_text

    messages = [
        {"role": "system", "content": _system_prompt},
        {"role": "user", "content": user_content},
    ]

    _adapter.ensure_ready()

    print("[llm_brain] Sending to LLM...")
    response = _adapter.complete_with_tools(messages, GAIT_TOOLS)

    print(f"[llm_brain] Response received — has tool_calls: {bool(response.get('tool_calls'))}")
    if response.get("tool_calls"):
        names = [tc["function"]["name"] for tc in response["tool_calls"]]
        print(f"[llm_brain] Tool call(s) requested: {names}")
    if response.get("content"):
        print(f"[llm_brain] Content: {response['content'][:200]}")

    if not response.get("tool_calls"):
        print("[llm_brain] WARNING: model did not choose a tool")
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

    print(f"[llm_brain] Executing: {function_name}({arguments})")
    result = execute_tool(function_name, arguments)
    print(f"[llm_brain] Execution result: {result}")

    return {"tool_chosen": function_name, "execution_result": result}
