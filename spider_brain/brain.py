"""
brain.py — decides what the robot should do next.

THIS IS THE SEAM. Everything else in spider_brain (server.py, robot_client.py)
stays exactly the same whether decide_next_action() is a mock or a real LLM
call. Only this file changes when we wire up llama.cpp.

Current implementation: MOCK. Cycles through a fixed sequence, ignoring
sensors/history entirely, so we can prove the full pipeline
(PC -> robot relay -> servos) works before an LLM is anywhere near it.
"""

import itertools
from typing import List

MOCK_ACTION_SEQUENCE = ["stand", "forward", "forward", "turn left", "forward", "sit"]
_action_cycle = itertools.cycle(MOCK_ACTION_SEQUENCE)


def decide_next_action(sensors: dict, history: List[str]) -> str:
    """
    Return the next gait action to send to the robot.

    Args:
        sensors: latest reading from GET /sensors on the robot
                 (e.g. {"ultrasonic_cm": 17.9, "timestamp": ...})
        history: list of actions already taken this session, most recent last

    Returns:
        One of the action strings the robot relay accepts:
        "stand", "sit", "forward", "backward", "turn left", "turn right"

    --- SWAP POINT FOR THE LLM ---
    The future version will do roughly:
        prompt = build_prompt(sensors, history)
        response = call_llama_cpp(prompt)   # OpenAI-compatible API, Docker
        action = parse_action(response)
        return action
    Same inputs, same return type — nothing outside this file needs to change.
    """
    return next(_action_cycle)
