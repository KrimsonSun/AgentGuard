# AgentGuard 运行时镜像（Fly.io，常驻单机跑两进程：代理 + console）
FROM python:3.12-slim

WORKDIR /app

# 先装依赖（利用 Docker 层缓存）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 拷业务代码（媒体栈已退役，不含 livekit）
COPY app/ ./app/
COPY vapi/ ./vapi/
COPY admin/ ./admin/
COPY db/ ./db/
COPY start.sh .
RUN chmod +x start.sh

# 8200=custom-llm 代理+工具(公网给 Vapi)；8100=admin console(私有，走 fly proxy)
EXPOSE 8200 8100

CMD ["./start.sh"]
