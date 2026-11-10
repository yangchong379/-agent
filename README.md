# 企业级求职与面试 Agent V3

一个基于 FastAPI 和 LangGraph 的求职与模拟面试 Agent。它提供简历与岗位匹配、面试追问与评分、知识库检索和人工复核，并保留会话状态与审计记录。

本地可使用 Mock 模式体验流程。模型服务的密钥通过本机 `.env` 配置，仓库提供 `.env.example` 作为模板。

## 1. 你将得到什么

- FastAPI 企业接口和自动 API 文档；
- `X-API-Key + X-Tenant-ID` 的租户鉴权与数据隔离；
- 候选人授权、PII 脱敏、提示注入标记；
- LangGraph 有界工作流，不在节点中调用 `input()`；
- Pydantic 结构化输出，不再靠脆弱的字符串 JSON 修复；
- Mock、DashScope、OpenAI 三种模型适配器；
- 本地可审计 RAG，可逐步替换为 pgvector/OpenSearch；
- 统一 100 分制，并由程序计算总分；
- 人工审批门，模型不能自动录用或淘汰；
- 2～6 轮自适应面试，追问读取之前轮次的上下文与评分；
- 求职教练持续对话，组合最近消息、滚动摘要、简历、JD 与长期记忆；
- 长期记忆支持敏感信息过滤、去重、租户/用户双层隔离及查看、修改、删除；
- 求职教练页支持直接粘贴或上传 PDF/TXT/Markdown 简历，并自动关联最近一份简历；
- 确定性意图路由与本地岗位匹配，输出匹配分和命中关键词，结果不依赖模型猜测；
- DashScope/OpenAI 调用失败时自动降级到本地 Mock，保证核心流程不中断；
- 低输入求职模式：自动读取最近简历，并通过岗位推荐、差距分析、简历优化、模拟面试和 7 天计划快捷按钮完成常见任务；
- SQLite 本地开发、PostgreSQL 容器部署、Alembic 迁移；
- JSON 日志、请求 ID、审计日志；
- 单元测试、接口全流程测试和检索评测；
- 从旧 V2 安全迁移岗位数据与导出 Chroma 知识的脚本。

## 2. 系统工作方式

```text
客户端
  │ API Key + Tenant ID
  ▼
FastAPI ── 输入校验 / 授权 / 脱敏 / 请求ID
  │
  ├─ 意图路由（本地规则）
  ├─ 岗位匹配（本地可解释评分）
  ├─ 上下文组装（简历 / 对话 / 记忆 / JD）
  ├─ 千问生成（失败时本地降级）
  ├─ 简历结构化
  ├─ 简历与 JD 匹配分析
  ├─ 内部知识检索（带 evidence_id）
  ├─ 生成首题
  ├─ 首答评分 → 生成追问
  └─ 追答评分 → 生成报告
                     │
                     ▼
                人工审核批准/拒绝
                     │
                     ▼
             PostgreSQL + Audit Log
```

LangGraph 在这里负责固定、可观察的准备流程。面试交互状态放在数据库中，不让一个进程长时间阻塞等待用户输入。这比把 20 多个节点线性串起来并在节点内部使用 `input()` 更适合 Web 服务。

## 3. 五个必须掌握的基础概念

### 3.1 LLM 不是业务系统

LLM 是一个根据上下文预测输出的概率模型。它可能编造、格式漂移，也会受到输入中恶意指令影响。因此：

- 模型负责语义任务：提取、比较、提问、解释；
- 程序负责确定性任务：权限、总分、状态流转、幂等、数据库约束；
- 人负责高风险决策：录用、淘汰、薪酬、例外处理。

### 3.2 Agent = 模型 + 工具 + 状态 + 控制循环

只有一次模型调用不是完整 Agent。一个可落地 Agent 至少要回答：当前目标是什么、有哪些工具、状态存在哪里、下一步如何选择、何时停止、失败后怎样恢复、谁可以批准副作用。

本项目故意使用“有界工作流”，而不是无限自主循环。招聘场景风险较高，可预测性和审计性比炫技更重要。

### 3.3 Structured Output

输出必须先通过 Pydantic Schema。即使模型说“总分 95”，程序仍会重新按五个维度求和。模型输出只是一份待验证的数据，不是可信指令。

### 3.4 RAG 与证据

RAG 的过程是：切分内部文档 → 检索相关片段 → 把片段和来源 ID 提供给模型 → 输出引用。RAG 不能自动保证答案正确；还要测试检索召回率、禁止伪造引用、定期更新知识和权限过滤。

### 3.5 Evals

Agent 的质量不能只靠“看起来不错”。至少要持续测：

- 结构化输出通过率；
- 检索 Recall@K；
- 评分与人工评分的一致性；
- 幻觉和错误引用率；
- 提示注入防御；
- 跨租户数据泄露；
- 延迟、模型费用、失败重试率。

## 4. Windows 本地运行（推荐先用 Mock）

要求 Python 3.11 和 PowerShell 7。首次运行时克隆仓库，再执行初始化脚本。

```powershell
git clone https://github.com/yangchong379/-agent.git
Set-Location -LiteralPath .\-agent
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\bootstrap.ps1
```

脚本会创建虚拟环境、安装依赖、生成随机 API Key、执行测试。然后启动：

```powershell
.\scripts\run.ps1
```

打开：

- API 文档：<http://127.0.0.1:8000/docs>
- 健康检查：<http://127.0.0.1:8000/health>

### 推荐：使用网页工作台

启动后直接打开：

```text
http://127.0.0.1:8000/
```

系统会进入 `/ui/login`。登录时填写：

- 企业标识：本地测试使用 `demo-company`；
- 应用访问密钥：`.env` 中 `APP_API_KEY=` 后面的值，不是 DashScope Key。

### 从简历推荐岗位方向并查看招聘链接

进入「求职教练」，上传简历或选择已保存简历。页面会根据简历中明确出现的技能与项目词汇推荐岗位方向，并展示推荐依据。选定方向后可选填目标城市；留空会展示所有地区的已有岗位。点击「查找这个方向的招聘信息」，结果页直接展示职位名称、公司、地点、要求、来源和岗位详情链接，不再只提供搜索引擎入口。实时招聘接口需要具体城市，因此留空时不会调用接口。岗位状态以原始职位页面为准。

无需接口密钥，求职教练会在打开结果页时查询海尔官方 2027 校招岗位列表，再读取匹配岗位的官方详情，直接显示岗位信息。该实时来源只覆盖海尔，不能代表青岛或全国全部企业；官方接口不可用、活动结束或无匹配岗位时会给出提示。页面也会显示深圳/青岛的部分人工核查岗位快照（注明核查日期），以及工作台中手工保存且附有原始链接的岗位。快照不是实时检索，不保证仍在招。查询仅发送岗位方向关键词和城市，不发送简历原文。

若 `.env` 已配置 `DASHSCOPE_API_KEY`，可在方向选择表单勾选「使用千问联网扩展搜索」。该操作可能产生百炼 API 费用，需填写城市，每次勾选查询时才调用。它使用千问的联网搜索获取候选来源链接，但**不采信模型生成的职位结论**：仅从允许的具体职位详情页读取并核对职位词和城市后，才加入岗位卡片。招聘平台可能要求登录、阻止自动读取，或返回不相关页面；这类结果会被排除，因此千问搜索可能新增 0 条。只发送岗位方向和城市，不发送简历原文。参见[百炼联网搜索官方文档](https://help.aliyun.com/zh/model-studio/web-search/)。

在岗位卡片点击「保存岗位并分析匹配」，可直接保存带来源链接的岗位摘要、查看简历技能证据覆盖率与缺口，并进入关联岗位的求职辅导对话或面试练习。具体原理、评分局限和项目面试讲法见 [docs/coach_job_flow_cn.md](docs/coach_job_flow_cn.md)。

如需跨企业的更广覆盖，可另外配置 [Jooble 对应地区的 REST API](https://help.jooble.org/en/support/solutions/articles/60001448238-rest-api-documentation)。先确认 Jooble 在目标国家/地区提供服务，再在对应地区的 API 页面申请密钥，例如香港地区为 <https://hk.jooble.org/api/about>，然后在本项目的 `.env` 中填写：

```text
JOOBLE_API_KEY=你的地区密钥
JOOBLE_API_HOST=hk.jooble.org
```

不同地区需要各自的密钥；将 `JOOBLE_API_HOST` 改为密钥所属地区的 `jooble.org` 域名。配置后重启服务，即可在岗位卡片中加入接口返回的实时岗位。Jooble 不应被默认视为覆盖中国大陆城市；青岛等城市目前由海尔官方实时来源和岗位快照提供信息。若没有 API 密钥，页面仍可查询海尔校招，并展示上述岗位快照和已保存岗位。

登录后按照页面上的三个步骤操作：

1. 粘贴经过候选人授权的简历；
2. 创建岗位；
3. 选择简历和岗位并发起面试。

面试创建后，工作台会生成一个24小时有效的候选人链接。候选人打开链接即可回答首题和追问，不会看到 API Key、Tenant ID、JSON、评分标准或内部数据库 ID。回答完成后，内部人员在“查看报告与审核”页面核对原始回答、评分依据和最终报告，再批准或退回。

网页使用签名会话、CSRF校验、HttpOnly Cookie和限时邀请链接。当前登录仍是本地 MVP 的 API Key 登录；正式企业部署应替换为 OIDC/SSO，并为管理员、面试官和审核人配置独立角色权限。

查看 `.env` 中自动生成的 `APP_API_KEY`。后续示例先设置：

```powershell
$apiKey = (Get-Content .env | Where-Object { $_ -like 'APP_API_KEY=*' }).Split('=', 2)[1]
$headers = @{ "X-API-Key" = $apiKey; "X-Tenant-ID" = "demo-company" }
```

## 5. 完整 API 操作

### 第一步：录入已授权简历

```powershell
$resume = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/resumes `
  -Headers $headers -ContentType "application/json; charset=utf-8" `
  -Body (@{
    source_name = "candidate-001.txt"
    resume_text = "三年 Java 后端经验，负责 Spring Boot、MySQL、Redis 性能优化项目。"
    consent = $true
  } | ConvertTo-Json)
$resume | ConvertTo-Json -Depth 10
```

生产中必须保存授权依据和隐私政策版本。目前这个基线只保存授权时间，后续应接入企业 IAM 与同意书系统。

### 第二步：录入合法获得的 JD

```powershell
$job = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/jobs `
  -Headers $headers -ContentType "application/json; charset=utf-8" `
  -Body (@{
    title = "Java 后端工程师"
    company = "示例企业"
    city = "深圳"
    jd_text = "负责核心交易系统，要求 Java、MySQL、缓存和高并发故障排查经验。"
    source_type = "user_provided"
  } | ConvertTo-Json)
```

V3 没有把匿名爬虫放进生产主链路。企业应使用用户提供、已授权 API 或已验证来源的职位数据。

### 第三步：创建面试

```powershell
$run = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/interviews `
  -Headers $headers -ContentType "application/json; charset=utf-8" `
  -Body (@{
    resume_id = $resume.id
    job_id = $job.id
    idempotency_key = "candidate-001-java-001"
  } | ConvertTo-Json)
$run.turns[0].question
```

`idempotency_key` 可以防止网络重试时重复创建一次面试。

### 第四步：提交首答

```powershell
$run = Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/interviews/$($run.id)/answers" `
  -Headers $headers -ContentType "application/json; charset=utf-8" `
  -Body (@{
    answer = "我先建立 P99 延迟和吞吐基线，再通过 GC 日志和火焰图定位，最后使用相同流量压测验证。"
  } | ConvertTo-Json)
$run.turns[1].question
```

### 第五步：提交追答并生成报告

```powershell
$run = Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/interviews/$($run.id)/answers" `
  -Headers $headers -ContentType "application/json; charset=utf-8" `
  -Body (@{
    answer = "保持环境和数据量一致，比较 P99、错误率、吞吐和资源利用率，并执行回归测试。"
  } | ConvertTo-Json)
$run.final_report | ConvertTo-Json -Depth 10
```

此时状态必须是 `pending_human_review`。

### 第六步：人工复核

```powershell
$reviewed = Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/interviews/$($run.id)/review" `
  -Headers $headers -ContentType "application/json; charset=utf-8" `
  -Body (@{
    decision = "approved"
    reviewer = "reviewer-001"
    comment = "已核对原始回答和评分证据"
  } | ConvertTo-Json)
$reviewed.status
```

这里的 `approved` 表示“报告通过人工复核”，不应直接等同于“录用候选人”。

## 6. 切换真实模型

### 使用通义千问

编辑 `.env`：

```dotenv
LLM_PROVIDER=dashscope
LLM_MODEL=qwen-plus
DASHSCOPE_API_KEY=新创建的Key
```

重启服务。不要把 Key 写进 Python 文件或提交 Git。

启用后，服务会把完成基础 PII 脱敏后的相关简历文本、岗位内容、当前消息、近期上下文和召回记忆发送给阿里云 DashScope。原始上传文件不会直接发送，但姓名、项目描述等未被规则识别的信息仍可能包含在文本中，因此处理真实个人简历前必须取得本人同意并遵守适用的数据与隐私要求。

### 使用 OpenAI

```dotenv
LLM_PROVIDER=openai
LLM_MODEL=你的可用模型名称
OPENAI_API_KEY=你的Key
```

OpenAI 适配器使用 Responses API 的 Pydantic 结构化解析。不同账号可用模型可能不同，以账号控制台和官方文档为准。

## 7. 运行测试与评测

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe scripts\smoke_test.py
.\.venv\Scripts\python.exe scripts\evaluate_retrieval.py
```

测试包括：PII 脱敏、提示注入标记、确定性评分、检索相似度、LangGraph 工作流、完整 API 生命周期、租户隔离。

增加模型提示词、工具或知识库后，都要把真实失败案例匿名化后加入 `evals/cases.jsonl` 或新的测试文件。没有回归评测，就无法知道一次“优化”是否让别的场景变差。

## 8. 从 V2 迁移

### 8.1 先备份

备份 V2 的数据目录。V3 读取旧库并写入新库，示例命令中的源路径需替换为实际位置。

### 8.2 迁移已有职位

先启动过一次 V3 或执行数据库迁移，然后：

```powershell
.\.venv\Scripts\python.exe scripts\import_v2.py `
  --source ".\path-to-v2\database\interview.db" `
  --target "sqlite:///./data/agent_v3.db" `
  --tenant "demo-company"
```

脚本只导入带 JD 的职位并去重。旧面试记录可能含候选人个人信息，必须先建立用户映射、取得迁移授权、确定保留期限，因此不会自动导入。

### 8.3 导出旧 Chroma 知识

```powershell
.\.venv\Scripts\python.exe scripts\export_v2_knowledge.py `
  --chroma-dir ".\path-to-v2\chroma-db" `
  --output "knowledge\imported_v2.md"
```

上线前逐条审阅导出的内容，删除个人信息、过期材料、许可证不明确的内容，然后重新运行检索评测。

## 9. Docker + PostgreSQL

将 `.env.example` 复制为 `.env`，至少修改：

- `APP_ENV=production`
- `APP_API_KEY`：不少于 24 字符的随机值；
- `TENANT_API_KEYS_JSON`：租户到独立密钥的 JSON，例如 `{"company-a":"key-a","company-b":"key-b"}`；
- `POSTGRES_PASSWORD`：独立随机值；
- 模型提供商和对应 Key。

然后：

```powershell
docker compose up --build
```

容器会先执行 `alembic upgrade head`，再启动 API。这个 Compose 文件适合开发/演示，不等同于完整生产平台。

## 10. 企业上线的正确顺序

### 阶段 A：小范围内部试点

1. 明确一个场景：例如 Java 后端初面辅助，不要一开始覆盖全公司；
2. 确定业务负责人、数据负责人、安全负责人和人工审核人；
3. 建立 50～200 个匿名化黄金样本，由资深面试官给出参考结果；
4. 在 Mock 和测试环境跑通全链路；
5. 接真实模型，对照人工结果测质量、成本和延迟；
6. 影子运行两周，只生成建议，不影响真实决策。

### 阶段 B：生产工程化

1. API Key 换成企业 SSO/OIDC，服务身份使用短期凭证；
2. PostgreSQL 开启备份、加密、最小权限和连接池；
3. RAG 换成带租户过滤、访问控制和版本管理的向量服务；
4. 长任务放入队列，增加超时、重试、死信和取消；
5. 接 OpenTelemetry、指标、追踪和告警；
6. 建立模型调用预算、速率限制、缓存和降级策略；
7. 做 SAST、依赖扫描、镜像扫描、渗透测试和提示注入红队；
8. 定义数据保留与删除 SLA，支持候选人访问和删除请求；
9. 模型/提示词/知识库每次变更都经过版本化、离线评测和灰度；
10. 高风险动作继续由人批准，并记录审批依据。

### 阶段 C：规模化

只有当单 Agent 的质量、成本、审计和恢复机制稳定后，再考虑多 Agent。多 Agent 适合真正可以并行且边界清楚的职责，例如“资料核验”“技术面试”“评测质检”。不要为了概念新颖而引入额外协调复杂度。

## 11. 目录说明

```text
app/
  api/          HTTP 接口、鉴权、租户上下文
  core/         日志、安全与脱敏
  db/           SQLAlchemy 模型和连接
  llm/          模型统一接口及三种 Provider
  schemas/      Pydantic 输入输出契约
  services/     检索、评分等确定性业务逻辑
  workflows/    LangGraph 有界工作流
alembic/        数据库版本迁移
knowledge/      经授权、可审计的内部知识
evals/          评测数据集
scripts/        启动、迁移、导出与评测脚本
tests/          自动化测试
```

## 12. 仍需企业按自身情况完成的内容

这个仓库是可运行基线，不可能代替企业治理。正式上线前还需要：法律与招聘合规评审、数据分级、SSO/RBAC、密钥托管、云资源、域名和 TLS、监控平台、备份恢复演练、事件响应、人工申诉流程、公平性评测，以及与你所在地区相符的隐私与 AI 法规评估。

继续学习请看 `docs/LEARNING_GUIDE.md`，上线评审时逐项执行 `docs/PRODUCTION_CHECKLIST.md`。

如果需要把项目写进简历并准备项目面试，请阅读 `docs/RESUME_PROJECT_GUIDE.md`。该文档解释了完整数据流、上下文与记忆原理、设计取舍、简历描述和常见追问。

## 13. 设计参考

- OpenAI Production best practices：密钥、环境隔离、扩缩容与限额；
- OpenAI Structured Outputs：用 Schema 约束模型输出；
- OpenAI Guardrails and approvals：工具安全与人工批准；
- OpenAI Agent evals：使用可复现评测改进 Agent。

对应官方地址：

- <https://developers.openai.com/api/docs/guides/production-best-practices>
- <https://developers.openai.com/api/docs/guides/structured-outputs>
- <https://developers.openai.com/api/docs/guides/agents/guardrails-approvals>
- <https://developers.openai.com/api/docs/guides/agent-evals>
