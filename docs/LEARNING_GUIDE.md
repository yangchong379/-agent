# 从代码真正理解 Agent：学习路线与实验

建议不要从头到尾背代码，而是按下面 8 个实验逐步修改、运行、观察。每一步都对应企业 Agent 的一个核心能力。

## 实验 1：先理解普通 LLM 调用

打开 `app/llm/base.py`。`StructuredLLM` 只有一个职责：给定系统约束、用户数据和 Schema，返回一个通过验证的对象。

关键认识：

1. system prompt 定义规则；
2. user content 放不可信业务数据；
3. schema 定义机器可处理的输出合同；
4. Provider 负责把统一合同翻译成供应商 API。

先保持 `LLM_PROVIDER=mock` 运行烟雾测试。再切换 DashScope，对比输出，但不要改业务代码。这就是“依赖倒置”：业务依赖统一接口，不依赖某一家模型。

## 实验 2：观察结构化输出

打开 `app/schemas/domain.py`，把 `JobAnalysis.fit_score` 的上限临时改成 60，运行测试，再恢复。你会看到 Pydantic 在模型边界阻止非法结果。

Schema 解决的是“格式可用”，不保证“语义正确”。语义正确仍需要证据、评测和人工复核。

## 实验 3：理解确定性与概率性的边界

阅读 `app/services/scoring.py` 和 `app/workflows/interview.py`：

- 模型输出五个评分维度；
- `dimension_total()` 由程序求和；
- `final_score()` 固定使用 75% 首答 + 25% 追答；
- 模型写出的总分会被覆盖。

企业系统应尽量把金额、权限、状态、总分、限额和时间计算放在确定性代码中。

## 实验 4：理解状态机

一次面试依次经过：

```text
awaiting_initial_answer
  → awaiting_followup_answer
  → pending_human_review
  → review_approved 或 review_rejected
```

状态保存在 `interview_runs.status`。接口会拒绝不合法跳转，例如在首答之前直接审核。

请尝试：创建面试后直接调用 `/review`，确认得到 HTTP 409。这就是状态机在保护业务不变量。

## 实验 5：理解 RAG

`app/services/retrieval.py` 做了四件事：

1. 读取 `knowledge/*.md`；
2. 切成重叠片段；
3. 为每片生成稳定 evidence ID；
4. 计算查询与片段相似度，返回 Top K。

当前算法是透明、零外部服务的字符 n-gram 基线，适合学习和小数据验证。规模化时可以换 pgvector/OpenSearch，但对外接口 `search(query, top_k)` 不变。

自己新增一篇知识文档，再在 `evals/cases.jsonl` 增加问题和关键字，运行 `scripts/evaluate_retrieval.py`。如果新文档没被召回，优先修检索，不要仅靠加长 Prompt。

## 实验 6：理解 Prompt Injection

简历、JD、回答和知识库都可能包含“忽略之前指令”之类文本。`DATA_RULE` 明确把它们视为数据；`detect_prompt_injection()` 会做风险标记；秘密只从服务端环境变量读取，不进入 Prompt。

这不是绝对防护。生产中还应：

- 给工具调用设置参数 Schema 和权限；
- 高风险工具调用前要求人工批准；
- 输出到 HTML/SQL/命令行前做上下文编码；
- 对跨租户检索在数据库层强制过滤；
- 用攻击样本持续红队和回归。

## 实验 7：理解可观测性

每个请求有一个 `X-Request-ID`，日志和 `audit_logs` 可以关联。同一错误对用户只返回通用信息，详细堆栈只进入服务端日志。

生产中继续增加：模型名、提示词版本、知识库版本、Token 数、延迟、重试、工具名和结果状态。不要记录原始简历、回答、API Key 或完整 Prompt。

## 实验 8：理解评测驱动开发

建立三层评测：

1. 单元测试：脱敏、评分、状态机等确定性逻辑；
2. 离线数据集：检索、提取、问答、评分与黄金样本比较；
3. 线上观察：人工改判率、失败率、延迟、费用、公平性投诉。

推荐给每次发布生成一张对比表：

| 指标 | 当前生产 | 候选版本 | 门槛 |
|---|---:|---:|---:|
| 结构化成功率 | 99.5% | 99.7% | ≥99% |
| 检索 Recall@4 | 90% | 93% | ≥90% |
| 人工评分相关性 | 0.82 | 0.84 | ≥0.80 |
| P95 延迟 | 8.1s | 8.6s | ≤10s |
| 单次成本 | ¥0.18 | ¥0.20 | ≤¥0.25 |

指标门槛要由业务、安全和工程共同确定。

## 从单 Agent 到多 Agent 的判断标准

只有同时满足以下条件才拆分：

- 子任务真的能够独立执行或并行；
- 每个角色有清晰输入、输出和权限；
- 单 Agent 已出现可测量的上下文过长或职责冲突；
- 有统一协调器、超时、预算和失败恢复；
- 多 Agent 版本在评测中显著优于单 Agent。

否则，优先保留当前这种清晰的有界工作流。

## 推荐学习顺序

1. Python 类型、异常、模块、虚拟环境；
2. HTTP、REST、JSON、鉴权；
3. Pydantic 和 FastAPI；
4. SQL、事务、索引、SQLAlchemy、Alembic；
5. LLM Prompt、Token、采样、Structured Output；
6. Embedding、相似度、切分、RAG；
7. 状态机、幂等、队列、重试；
8. Evals、Tracing、监控；
9. 安全、隐私、合规、人机协作；
10. 最后再学多 Agent 和复杂规划。

