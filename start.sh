#!/bin/bash
# 单机跑两进程：代理(公网) + console(私有)。任一进程挂掉即退出，让 Fly 重启机器。
set -e
uvicorn vapi.tools_server:app --host 0.0.0.0 --port 8200 &
uvicorn admin.server:app     --host 0.0.0.0 --port 8100 &
wait -n
exit $?
