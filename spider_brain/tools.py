"""
tools.py — OpenAI-format tool definitions for the robot's known-good gait
actions, plus the executor that turns a chosen tool into a real robot
command. Only actions verified against picrawler's real API are exposed
here — matches VALID_ACTIONS in the robot's relay_server.py.
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
    """Turn an LLM tool call into a real /gait command on the robot."""
    action = TOOL_NAME_TO_ACTION.get(tool_name)
    if action is None:
        return {"error": f"unknown tool: {tool_name}"}
    try:
        result = robot_client.send_gait(action)
        return {"status": "executed", "action": action, "robot_response": result}
    except Exception as e:
        return {"error": str(e)}
