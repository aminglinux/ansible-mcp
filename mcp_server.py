import asyncio
import json
import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, FastAPI
from fastapi.responses import StreamingResponse
from fastapi_mcp import FastApiMCP
from pydantic import BaseModel

router = APIRouter(prefix="/tools", tags=["ansible"])
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
PLAYBOOKS_DIR = os.path.join(BASE_DIR, "playbooks")
DEFAULT_TIMEOUT = 60

# ========================
# 数据模型
# ========================
class AdHocInput(BaseModel):
    host: str
    module: str
    args: str
    inventory: Optional[str] = "inventory.ini"

class PlaybookInput(BaseModel):
    playbook: str           # e.g. ./site.yml
    inventory: Optional[str] = "inventory.ini"
    extra_vars: Optional[Dict[str, Any]] = None

class InventoryInput(BaseModel):
    inventory: str = "inventory.ini"

class ValidatePlaybookInput(BaseModel):
    playbook: str


class PlaybookGenerateInput(BaseModel):
    file_name: str
    data: str


def _build_ansible_env() -> Dict[str, str]:
    env = os.environ.copy()
    env.setdefault("ANSIBLE_FORCE_COLOR", "0")
    env.setdefault("ANSIBLE_HOST_KEY_CHECKING", "False")
    return env


async def run_ansible_command(cmd: list[str], timeout: int = DEFAULT_TIMEOUT) -> Dict[str, Any]:
    """
    Execute an Ansible CLI command with default environment and timeout protection.
    """
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=_build_ansible_env(),
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout)
        return {
            "stdout": stdout.decode(),
            "stderr": stderr.decode(),
            "returncode": proc.returncode,
        }
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        return {
            "stdout": "",
            "stderr": f"Command timed out after {timeout}s",
            "returncode": None,
            "timeout": True,
        }

# ========================
# 工具：列出 Inventory 主机组／结构
# ========================
@router.post("/list_inventory", operation_id="list_inventory")
async def list_inventory(input: InventoryInput):
    inventory_file = input.inventory
    if not os.path.exists(inventory_file):
        return {"error": f"Inventory file not found: {inventory_file}"}
    cmd = ["ansible-inventory", "-i", inventory_file, "--list"]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        return {"stderr": stderr.decode(), "returncode": proc.returncode}
    try:
        return json.loads(stdout.decode())
    except json.JSONDecodeError:
        return {"output": stdout.decode()}

# ========================
# 工具：列出主机（host）清单
# ========================
@router.post("/list_hosts", operation_id="list_hosts")
async def list_hosts(input: InventoryInput):
    inventory_file = input.inventory
    cmd = ["ansible", "all", "-i", inventory_file, "--list-hosts"]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()
    return {
        "stdout": stdout.decode(),
        "stderr": stderr.decode(),
        "returncode": proc.returncode,
    }

# ========================
# 工具：validate playbook
# ========================
@router.post("/validate_playbook", operation_id="validate_playbook")
async def validate_playbook(input: ValidatePlaybookInput):
    playbook = input.playbook
    if not os.path.exists(playbook):
        return {"error": f"Playbook not found: {playbook}"}
    # 使用 ansible-playbook --syntax-check 或 ansible-lint（如果安装了）
    cmd = ["ansible-playbook", playbook, "--syntax-check", "-i", "inventory.ini"]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()
    return {
        "stdout": stdout.decode(),
        "stderr": stderr.decode(),
        "returncode": proc.returncode,
    }

# ========================
# 工具：Ping 测试
# ========================
@router.post("/ping_hosts", operation_id="ping_hosts")
async def ping_hosts(input: InventoryInput):
    cmd = ["ansible", "all", "-m", "ping", "-i", input.inventory]
    # Limit runtime so SSH prompts or unreachable hosts do not block the API indefinitely.
    return await run_ansible_command(cmd, timeout=30)

# ========================
# 工具：执行 Ad-Hoc
# ========================
@router.post("/run_ad_hoc", operation_id="run_ad_hoc")
async def run_ad_hoc(input: AdHocInput):
    cmd = [
        "ansible", input.host,
        "-m", input.module,
        "-a", input.args,
        "-i", input.inventory
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()
    return {
        "stdout": stdout.decode(),
        "stderr": stderr.decode(),
        "returncode": proc.returncode,
    }

# ========================
# 工具：获取 ansible 版本
# ========================
@router.get("/ansible_version", operation_id="get_ansible_version")
async def get_ansible_version():
    proc = await asyncio.create_subprocess_exec(
        "ansible", "--version",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, _ = await proc.communicate()
    first_line = stdout.decode().splitlines()[0] if stdout else ""
    return {"version": first_line}


# ========================
# 工具：生成 Playbook 文件
# ========================
@router.post("/generate_playbook", operation_id="generate_playbook")
async def generate_playbook(input: PlaybookGenerateInput):
    sanitized_name = os.path.basename(input.file_name.strip())
    if not sanitized_name:
        return {"error": "file_name must be provided"}

    os.makedirs(PLAYBOOKS_DIR, exist_ok=True)
    target_path = os.path.join(PLAYBOOKS_DIR, sanitized_name)

    def _write_file():
        with open(target_path, "w", encoding="utf-8") as fh:
            fh.write(input.data)

    await asyncio.to_thread(_write_file)
    return {"status": "written", "path": target_path}

# ========================
# 工具：执行 Playbook (SSE 流式)
# ========================
@router.post("/run_playbook", operation_id="run_playbook")
async def run_playbook(payload: PlaybookInput):
    playbook = payload.playbook
    inventory = payload.inventory or "inventory.ini"
    extra_vars = payload.extra_vars

    async def event_stream():
        yield "event: start\ndata: Starting playbook execution...\n\n"
        try:
            cmd = ["ansible-playbook", playbook, "-i", inventory]
            if extra_vars:
                # 转义 extra_vars 为 JSON 字符串
                ev_str = json.dumps(extra_vars)
                cmd.extend(["--extra-vars", ev_str])

            process = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
            )
            async for line in process.stdout:
                cleaned = line.decode().rstrip()
                if cleaned:
                    yield f"data: {json.dumps(cleaned)}\n\n"
            await process.wait()
            if process.returncode == 0:
                yield "event: complete\ndata: SUCCESS\n\n"
            else:
                yield f"event: error\ndata: Return code {process.returncode}\n\n"
        except Exception as e:
            yield f"event: error\ndata: {str(e)}\n\n"
        yield "event: end\ndata: done\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


def setup_mcp(app: FastAPI) -> FastApiMCP:
    """
    Register the tool router with FastAPI and expose it through MCP transports.
    """
    app.include_router(router)

    mcp = FastApiMCP(
        app,
        name="Ansible MCP Server (Extended)",
        description="Async Ansible utilities with inventory and playbook helpers",
    )
    # Expose both transports so different MCP-capable clients can connect.
    mcp.mount_http()
    mcp.mount_sse()
    return mcp
