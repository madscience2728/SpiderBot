"""
llm_brain.py — the real (non-mock) decision-maker.

No longer stateless. Each cycle now builds its message list from:
  [system prompt] + [seed/priming conversation] + [rolling history window] + [this cycle's observation]

and the model can call MULTIPLE tools in one turn (e.g. `speak` + `forward`
together) rather than being restricted to exactly one action -- see
tools.py's ALL_TOOLS / execute_tool for why `speak` is its own tool
instead of relying on the plain `content` field.

Context budget note: each cycle's observation includes a camera frame,
and Gemma 4's image tokens aren't free (a few hundred to over a thousand
tokens per frame, depending on resolution). Keeping every past frame in
history would blow an 8192-token context window fast, so historical user
turns have their image stripped down to a text placeholder -- only the
CURRENT cycle's turn carries the real image. The model still gets the
gist of what happened via its own past `speak`/tool-call turns, just not
a full photo album.

Per Gemma 4's own model card: in multi-turn history, only the model's
final response should be kept, not any thinking/channel content -- see
_strip_thinking_tags below. Thinking isn't enabled here today, but this
is defensive in case that changes later.
"""

import json
import re

from spider_brain.config_loader import load_system_prompt, load_seed_conversation
from spider_brain.llm_adapter import LLMAdapter
from spider_brain.tools import ALL_TOOLS, execute_tool

_adapter = LLMAdapter()
_system_prompt = load_system_prompt()
_seed_conversation = load_seed_conversation()

# Rolling window: how many past (user, assistant[, tool...]) cycles to keep.
# A blunt cap rather than precise token counting -- simple, and generous
# enough given images are stripped from all but the current turn.
MAX_HISTORY_CYCLES = 8

_history = []  # list of message dicts, grows one cycle at a time

_THINKING_TAG_RE = re.compile(r"<\|channel>thought.*?<channel\|>", re.DOTALL)


def _strip_thinking_tags(content: str) -> str:
    if not content:
        return content
    return _THINKING_TAG_RE.sub("", content).strip()


def _strip_image_from_user_turn(message: dict) -> dict:
    """Historical user turns keep only their text, not the image -- see
    module docstring on context budget."""
    content = message.get("content")
    if isinstance(content, list):
        text_parts = [part["text"] for part in content if part.get("type") == "text"]
        return {"role": "user", "content": " ".join(text_parts) + " [camera frame omitted from history]"}
    return message


def _trim_history():
    """Keep only the last MAX_HISTORY_CYCLES cycles. A cycle is a
    (user, assistant, tool*, ...) run -- we trim by counting user
    messages from the end rather than a flat message count, so we never
    cut a cycle in half (e.g. keeping an assistant's tool_calls message
    without the tool result messages that must follow it)."""
    global _history
    user_indices = [i for i, m in enumerate(_history) if m["role"] == "user"]
    if len(user_indices) > MAX_HISTORY_CYCLES:
        cutoff = user_indices[-MAX_HISTORY_CYCLES]
        _history = _history[cutoff:]


def decide_and_act(sensors: dict, image_base64: str = None) -> dict:
    """One full LLM-driven cycle: observe (sensors + camera frame) ->
    decide (one or more tool calls) -> act on each. Returns what happened,
    for logging/status.

    image_base64 is optional so this still works with the old sensors-only
    flow (or a test harness with no camera) -- when provided, it's sent as
    an image_url content part alongside the text, per llama.cpp's
    OpenAI-compatible vision format. Note: Ezra's project (where this
    adapter pattern comes from) never actually implemented image input
    despite having mmproj configured -- there was no reference code to
    mirror here, so this part is new, not ported.
    """
    print(f"\n[llm_brain] Sensors: {sensors}")

    user_text = f"Current sensor reading: {sensors}."

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

    current_turn = {"role": "user", "content": user_content}

    # Only the most recent user turn in _history (if any) still has its
    # real image; everything older than that was already stripped when it
    # got appended in a PRIOR cycle (see below) -- so building the message
    # list is just a concatenation, no extra stripping needed here.
    messages = (
        [{"role": "system", "content": _system_prompt}]
        + _seed_conversation
        + _history
        + [current_turn]
    )

    _adapter.ensure_ready()

    print("[llm_brain] Sending to LLM...")
    response = _adapter.complete_with_tools(messages, ALL_TOOLS)

    tool_calls = response.get("tool_calls") or []
    print(f"[llm_brain] Response received — {len(tool_calls)} tool call(s)")
    if response.get("content"):
        print(f"[llm_brain] Content: {response['content'][:200]}")

    # Strip the image out of THIS turn before it goes into history, so it
    # only ever counts as "current" once. Do this now, not next cycle --
    # simpler than tracking which historical entry is "the most recent one
    # that still needs stripping."
    _history.append(_strip_image_from_user_turn(current_turn))

    if not tool_calls:
        print("[llm_brain] WARNING: model did not choose any tool")
        # Still record the assistant's plain response (if any) so the
        # conversation stays coherent even on a no-tool-call turn.
        assistant_content = _strip_thinking_tags(response.get("content", ""))
        _history.append({"role": "assistant", "content": assistant_content})
        _trim_history()
        return {
            "action": None,
            "reason": "model did not choose a tool",
            "raw_content": response.get("content"),
        }

    # Build the assistant message with tool_calls exactly as the API
    # returned it (need the same tool_call ids for the tool-result
    # messages that follow, per the standard multi-turn tool-calling
    # convention).
    assistant_message = {
        "role": "assistant",
        "content": _strip_thinking_tags(response.get("content", "")) or None,
        "tool_calls": tool_calls,
    }
    _history.append(assistant_message)

    results = []
    for tool_call in tool_calls:
        function_name = tool_call["function"]["name"]
        try:
            arguments = json.loads(tool_call["function"]["arguments"])
        except (json.JSONDecodeError, KeyError):
            arguments = {}

        print(f"[llm_brain] Executing: {function_name}({arguments})")
        result = execute_tool(function_name, arguments)
        print(f"[llm_brain] Execution result: {result}")
        results.append({"tool_call_id": tool_call.get("id"), "name": function_name, "result": result})

        # One "tool" role message per call, referencing its id -- required
        # for the history to be valid on the next request.
        _history.append(
            {
                "role": "tool",
                "tool_call_id": tool_call.get("id"),
                "content": json.dumps(result),
            }
        )

    _trim_history()

    return {"tool_calls_made": [r["name"] for r in results], "results": results}
