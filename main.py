from fastapi import FastAPI

from mcp_server import setup_mcp

app = FastAPI(title="Ansible MCP Server (SSE & Tools)")
setup_mcp(app)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
