# 🧩 Ansible MCP Server (SSE Version)

一个兼容 Model Context Protocol (MCP) 的 Ansible 控制服务。
支持：
- Ansible ad-hoc 命令执行
- Playbook 执行（SSE 实时输出）
- Inventory 列表与 Ping 测试
- Ansible 版本查询

## 启动方式

### 本地运行
```bash
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8080
```

### Docker 运行
```bash
docker build -t ansible-mcp .
docker run -p 8080:8080 ansible-mcp
```

### 测试接口
```bash
curl -N -X POST http://localhost:8080/tools/run_playbook \
  -H "Content-Type: application/json" \
  -d '{"playbook":"./site.yml"}'
```

## 接入Dify/Coze
在 MCP 配置中填入： http://<your-host>:8080/.well-known/mcp.json
