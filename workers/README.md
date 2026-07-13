# Serverless 层 · Cloudflare Workers（设计稿）

> 状态：Day4+ 实现。对齐题目加分组合：GH Actions + CF Workers + OpenRouter + Neon。

## 门卫查询 API（加分项）

- **栈**：Hono + Neon serverless driver（HTTP，Workers 内可用）+ OpenRouter。
- **端点**：`POST /ask` —— 保安自然语言提问（"本周多少访客车？""张师傅这个月来了几次？"）。
- **实现**：单 agent 模式换入口——LLM 把 NL 翻成受限 SQL（只读角色 + 白名单表 + LIMIT），
  精确聚合出确定答案；不用向量/图近似（HANDOFF §决策1）。
- **记账**：每次调用同样写 usage_ledger（读/写 token 分列）。

## CI/CD

- GitHub Actions：lint + 部署 Workers（wrangler）+（可选）agent 镜像构建。
