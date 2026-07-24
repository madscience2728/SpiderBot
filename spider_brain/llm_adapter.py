"""
llm_adapter.py — minimal client for a local llama.cpp server running in
Docker. Pattern borrowed and simplified from the Ezra project's
docker_gemma4_adapter.py: same proven Docker command shape, same
OpenAI-compatible /v1/chat/completions + tool-calling approach.

Deliberately small: no async, no batching, no conversation-graph
machinery — just "send messages + tools, get back a decision."
"""

import requests

from spider_brain.config_loader import load_config

DOCKER_IMAGE = "ghcr.io/ggml-org/llama.cpp:server-cuda"


class LLMAdapter:
    def __init__(self):
        config = load_config()
        lm_config = config["llm_config"]

        self.base_url = lm_config["base_url"]
        self.model_name = lm_config["model_name"]
        self.mmproj = lm_config.get("mmproj")  # optional -- only present if vision is configured
        self.port = lm_config["port"]
        self.ctx_size = lm_config["ctx_size"]
        self.timeout = lm_config["timeout"]
        self.completions_url = f"{self.base_url}/v1/chat/completions"

    def assemble_docker_command(self) -> str:
        """Ready-to-run docker command — same proven shape as Ezra's,
        pulling model/port/context settings straight from config.json."""
        parts = [
            "docker run --rm --gpus all",
            f"-p {self.port}:{self.port}",
            '-v "${PWD}:/models"',
            DOCKER_IMAGE,
            f"--model /models/{self.model_name}",
        ]

        # Vision projector -- same as Ezra's adapter: only added if configured,
        # so this stays a no-op drop-in for anyone not using image input.
        if self.mmproj:
            parts.append(f"--mmproj /models/{self.mmproj}")

        parts.extend([
            "--host 0.0.0.0",
            f"--port {self.port}",
            "--n-gpu-layers 99",
            f"--ctx-size {self.ctx_size}",
            "--parallel 1",
            "--flash-attn on",
            "--jinja",  # required — enables the chat template tool-calling needs
        ])
        return " ".join(parts)

    def health_check(self, timeout: int = 5) -> bool:
        try:
            r = requests.get(f"{self.base_url}/v1/models", timeout=timeout)
            return r.status_code == 200
        except requests.exceptions.RequestException:
            return False

    def _not_running_message(self) -> str:
        return (
            "\nLLM Docker container is not running or not reachable.\n\n"
            "First time only — pull the image:\n\n"
            f"    docker pull {DOCKER_IMAGE}\n\n"
            "Then start the server with:\n\n"
            f"    {self.assemble_docker_command()}\n"
        )

    def ensure_ready(self):
        """Health check with a friendly, actionable message (including the
        one-time image pull) if the LLM container isn't up yet — same
        pattern as Ezra's DockerGemma4Adapter.load(), adapted to raise a
        normal exception instead of SystemExit, since this runs inside a
        FastAPI request and SystemExit would kill the whole server."""
        if not self.health_check():
            message = self._not_running_message()
            print(message)
            raise RuntimeError(message)

    def complete_with_tools(self, messages: list, tools: list) -> dict:
        """Send messages + tool definitions, get back either a tool call
        or plain content."""
        payload = {
            "model": self.model_name,
            "messages": messages,
            "tools": tools,
        }
        response = requests.post(self.completions_url, json=payload, timeout=self.timeout)
        response.raise_for_status()
        message = response.json()["choices"][0]["message"]

        if message.get("tool_calls"):
            return {"tool_calls": message["tool_calls"], "content": message.get("content", "")}
        return {"content": message.get("content", ""), "tool_calls": None}
