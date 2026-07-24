"""
tools.py — OpenAI-format tool definitions for the robot's known-good gait
actions, plus the executor that turns a chosen tool into a real robot
command. Only actions verified against picrawler's real API are exposed
here — matches VALID_ACTIONS in the robot's relay_server.py.

`speak` is included as its own tool rather than relying on the model's
plain `content` field for speech. Some chat templates only populate
`content` when there's no tool call, so a model calling `forward` might
not reliably also produce spoken text alongside it. Tool calls in
OpenAI-style APIs support multiple entries per turn (parallel tool
calls), so the model can call `speak` and `forward` together in one
response -- that's a template-independent mechanism, not something we're
hoping the model does opportunistically.
"""

from spider_brain import robot_client

GAIT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": {}},
        },
    }
    for name, description in [
        ("stand", "Make the robot stand up from a seated or resting position."),
        ("sit", "Make the robot sit down safely."),
        ("forward", "Move the robot forward one step."),
        ("backward", "Move the robot backward one step."),
        ("turn_left", "Turn the robot in place to the left."),
        ("turn_right", "Turn the robot in place to the right."),
    ]
]

SPEAK_TOOL = {
    "type": "function",
    "function": {
        "name": "speak",
        "description": (
            "Say something out loud through the robot's speaker. Use this to narrate "
            "what you see and why you're doing what you're doing -- you can call this "
            "in the SAME turn as a movement tool, so you can speak and act together."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "What to say, in natural spoken language."}
            },
            "required": ["text"],
        },
    },
}

ALL_TOOLS = GAIT_TOOLS + [SPEAK_TOOL]

# Tool names use underscores (required for function-calling names);
# map back to the actual gait strings the relay expects (which use spaces).
TOOL_NAME_TO_ACTION = {
    "stand": "stand",
    "sit": "sit",
    "forward": "forward",
    "backward": "backward",
    "turn_left": "turn left",
    "turn_right": "turn right",
}


def execute_tool(tool_name: str, arguments: dict) -> dict:
    """Turn an LLM tool call into a real robot command -- gait or speech."""
    if tool_name == "speak":
        text = arguments.get("text", "")
        try:
            result = robot_client.send_speak(text)
            return {"status": "spoke", "text": text, "robot_response": result}
        except Exception as e:
            return {"error": str(e)}

    action = TOOL_NAME_TO_ACTION.get(tool_name)
    if action is None:
        return {"error": f"unknown tool: {tool_name}"}
    try:
        result = robot_client.send_gait(action)
        return {"status": "executed", "action": action, "robot_response": result}
    except Exception as e:
        return {"error": str(e)}
