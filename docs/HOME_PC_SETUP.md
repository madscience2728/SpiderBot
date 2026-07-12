# SpiderBot — Home PC Setup Guide

This gets the "brain" side (spider_brain + local LLM) running on a second
machine. The robot itself (Pi) doesn't need any of this — it's already
self-contained and will just need its network settings updated once it's
physically moved (see the last section).

---

## 1. Get repository access

1. Accept the GitHub collaborator invite (check your email / GitHub notifications).
2. Clone the repo:
   ```
   git clone https://github.com/<owner-username>/SpiderBot.git
   cd SpiderBot
   ```
   (Use SSH instead if you've already got an SSH key set up with GitHub —
   either works.)
3. Work in a branch rather than pushing straight to main:
   ```
   git checkout -b buddy-home-setup
   ```

---

## 2. Verify WSL2 + Docker + GPU access

You mentioned WSL2 and Docker are already installed — this section is
mainly to confirm the GPU side actually works before we try running a
14GB model through it.

**Check the NVIDIA driver sees WSL2:**
```
wsl nvidia-smi
```
This should print your GPU name, driver version, and CUDA version. If it
errors or isn't found, install/update the standard NVIDIA driver from
nvidia.com (the normal Game Ready or Studio driver — modern versions
already include WSL2/CUDA support, no separate special download needed).
Do **not** install a separate NVIDIA driver *inside* WSL itself — the
Windows driver is passed through automatically, and installing a Linux
driver on top of that breaks things.

**Check Docker can actually reach the GPU:**
```
docker run --rm --gpus all nvcr.io/nvidia/k8s/cuda-sample:nbody nbody -gpu -benchmark
```
If this prints GPU benchmark numbers, Docker → WSL2 → GPU is fully wired
up and you're clear to move on. If it fails, Docker Desktop's WSL2
integration or GPU support isn't enabled — check Docker Desktop →
Settings → Resources → WSL Integration.

Official reference if anything above doesn't behave as expected:
https://docs.nvidia.com/cuda/wsl-user-guide/index.html

---

## 3. Set up the Python environment

```
cd spider_brain
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

---

## 4. Locate your LM Studio model and drop it into the project

LM Studio stores downloaded models here by default:
```
%USERPROFILE%\.lmstudio\models\<publisher>\<model-name>\<file>.gguf
```
Easiest way to find the exact path for real: open LM Studio → **My
Models** tab → it shows the path per model directly (this has moved
around between LM Studio versions, so trust the app over any doc).

Copy the `.gguf` file into the SpiderBot project root (the same folder
`docker run` will mount as `/models` — i.e. wherever you run the `docker
run` command from in step 6). Example:
```
copy "%USERPROFILE%\.lmstudio\models\<publisher>\<model>\<file>.gguf" .
```

---

## 5. Update config.json

Open `config/config.json` and set `model_name` to the **exact filename**
of the `.gguf` you just copied in (must match exactly, including
capitalization):
```json
{
  "llm_config": {
    "base_url": "http://localhost:8080",
    "model_name": "<your-actual-filename>.gguf",
    "port": 8080,
    "ctx_size": 8192,
    "timeout": 60
  }
}
```
Leave `base_url`/`port` alone unless you specifically want the Docker
container on a different port.

---

## 6. Start the LLM container

From the SpiderBot project root (same folder the `.gguf` is sitting in):
```
docker pull ghcr.io/ggml-org/llama.cpp:server-cuda
docker run --rm --gpus all -p 8080:8080 -v "${PWD}:/models" ghcr.io/ggml-org/llama.cpp:server-cuda --model /models/<your-actual-filename>.gguf --host 0.0.0.0 --port 8080 --n-gpu-layers 99 --ctx-size 8192 --parallel 1 --flash-attn on --jinja
```
(If `spider_brain` is running, hitting `/llm_step` before this container
is up will actually print this exact command back at you as an error
message — so this step is somewhat self-documenting going forward.)

---

## 7. Point spider_brain at the robot

The Pi will be on your home network by the time you're doing this, on a
different IP than at the shop. Set these (same pattern as before —
Windows env vars, not committed to git):
```
SPIDER_BOT_HOST = <the Pi's IP on your home network>
SPIDER_BOT_USER = spider
SPIDER_BOT_PASS = <ask for it>
```
Open a **new** terminal after setting these (env vars set via `setx`
don't apply to already-open terminals — and if you're setting them while
VS Code is open, fully restart VS Code too, not just the terminal panel).

Find the Pi's home IP the same way we did originally: try
`ping spiderbot.local` first, and if that doesn't resolve, check your
home router's connected-devices list.

---

## 8. Run it

```
python -m spider_brain
```

Test:
```powershell
Invoke-RestMethod http://localhost:9000/status
Invoke-RestMethod -Method Post http://localhost:9000/llm_step
```

Watch the `spider_brain` console for the `[llm_brain]` debug lines to
confirm the full round trip: sensors read → sent to the model → tool
chosen → executed on the robot.
