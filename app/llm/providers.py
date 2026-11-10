import json
import logging
import re
from typing import Any

from pydantic import BaseModel

from app.config import Settings
from app.llm.base import LLMError, SchemaT
from app.schemas.domain import (
    AnswerEvaluation,
    CareerCoachReply,
    ConversationSummary,
    FinalReport,
    FollowupQuestion,
    InterviewQuestion,
    JobAnalysis,
    MemoryCandidate,
    ResumeProfile,
    ScoreDimensions,
)


logger = logging.getLogger(__name__)


class MockStructuredLLM:
    """Deterministic local substitute used by tests and first-time setup."""

    def parse(
        self,
        *,
        system_prompt: str,
        user_content: str,
        schema: type[SchemaT],
    ) -> SchemaT:
        del system_prompt
        if schema is ResumeProfile:
            result: BaseModel = ResumeProfile(
                education=["信息来自候选人提供的简历"],
                skills=_keywords(user_content, 8),
                projects=["简历中描述的项目经历"],
                research_directions=[],
                evidence=[user_content[:120]],
            )
        elif schema is JobAnalysis:
            result = JobAnalysis(
                fit_score=70,
                evidence_quality="medium",
                confirmed_requirements=_keywords(user_content, 6),
                inferred_requirements=[],
                strengths=["具备与岗位相关的基础技能"],
                gaps=["需要通过面试验证项目深度"],
                interview_focus=["工程取舍", "故障排查"],
            )
        elif schema is InterviewQuestion:
            result = InterviewQuestion(
                question="请结合一个真实项目，说明你如何定位并解决高并发场景下的性能瓶颈？",
                topic="工程实践",
                difficulty="medium",
                expected_points=["指标", "定位过程", "方案取舍", "验证结果"],
                evidence_ids=["mock-evidence"],
            )
        elif schema is AnswerEvaluation:
            score = 10 if len(user_content) < 80 else 15
            dims = ScoreDimensions(
                relevance=score,
                correctness=min(30, score + 8),
                depth=score,
                engineering=score,
                communication=min(10, max(5, score - 5)),
            )
            result = AnswerEvaluation(
                dimensions=dims,
                total_score=sum(dims.model_dump().values()),
                strengths=["回答覆盖了问题核心"],
                weaknesses=["可补充量化指标和方案取舍"],
                evidence_from_answer=[user_content[:100]],
                feedback="建议按背景、行动、取舍、结果的顺序回答。",
            )
        elif schema is FollowupQuestion:
            result = FollowupQuestion(
                question="你用哪些指标证明优化有效，并如何排除偶然因素？",
                reason="验证候选人的量化分析与实验设计能力",
                expected_points=["基线", "监控指标", "对照实验", "回归验证"],
            )
        elif schema is FinalReport:
            result = FinalReport(
                initial_score=70,
                followup_score=70,
                final_score=70,
                strengths=["基础概念清晰"],
                weaknesses=["工程证据不足"],
                learning_plan=["补充可量化的项目复盘", "训练系统设计取舍表达"],
                decision_support_note="本报告只提供决策辅助，最终结论必须由人工审核。",
            )
        elif schema is CareerCoachReply:
            payload = json.loads(user_content)
            message = payload.get("current_user_message", "")
            remembered = payload.get("relevant_long_term_memories", [])
            memory_note = ""
            if remembered:
                memory_note = f"我会结合你此前确认的背景：{remembered[0]['content']}。"
            result = CareerCoachReply(
                reply=_mock_coach_reply(payload, message, memory_note),
                memory_candidates=_mock_memory_candidates(message),
            )
        elif schema is ConversationSummary:
            payload = json.loads(user_content)
            messages = payload.get("messages", [])
            snippets = [item.get("content", "")[:160] for item in messages[-8:]]
            previous = payload.get("previous_summary", "")
            result = ConversationSummary(
                summary="；".join(part for part in [previous, *snippets] if part)[-4000:]
            )
        else:
            raise LLMError(f"mock provider has no fixture for {schema.__name__}")
        return schema.model_validate(result.model_dump())


class OpenAIStructuredLLM:
    def __init__(self, settings: Settings) -> None:
        from openai import OpenAI

        kwargs: dict[str, Any] = {
            "api_key": settings.openai_api_key.get_secret_value(),
            "timeout": settings.llm_timeout_seconds,
            "max_retries": settings.llm_max_retries,
        }
        if settings.openai_base_url:
            kwargs["base_url"] = settings.openai_base_url
        self.client = OpenAI(**kwargs)
        self.model = settings.llm_model

    def parse(
        self,
        *,
        system_prompt: str,
        user_content: str,
        schema: type[SchemaT],
    ) -> SchemaT:
        response = self.client.responses.parse(
            model=self.model,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            text_format=schema,
        )
        parsed = response.output_parsed
        if parsed is None:
            raise LLMError("OpenAI response did not contain validated structured output")
        return parsed


class DashScopeStructuredLLM:
    def __init__(self, settings: Settings) -> None:
        from langchain_community.chat_models.tongyi import ChatTongyi

        self.model = ChatTongyi(
            model=settings.llm_model,
            dashscope_api_key=settings.dashscope_api_key.get_secret_value(),
            request_timeout=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
        )

    def parse(
        self,
        *,
        system_prompt: str,
        user_content: str,
        schema: type[SchemaT],
    ) -> SchemaT:
        from langchain_core.messages import HumanMessage, SystemMessage

        contract = json.dumps(schema.model_json_schema(), ensure_ascii=False)
        messages = [
            SystemMessage(
                content=f"{system_prompt}\n只返回一个 JSON 对象，不要 Markdown。JSON Schema：{contract}"
            ),
            HumanMessage(content=user_content),
        ]
        response = self.model.invoke(messages)
        content = response.content if isinstance(response.content, str) else str(response.content)
        try:
            return schema.model_validate(json.loads(content))
        except (json.JSONDecodeError, ValueError) as exc:
            match = re.search(r"\{.*\}", content, re.DOTALL)
            if match:
                try:
                    return schema.model_validate(json.loads(match.group(0)))
                except (json.JSONDecodeError, ValueError):
                    pass
            raise LLMError(f"DashScope returned invalid {schema.__name__}") from exc


class ResilientStructuredLLM:
    """Keeps the product usable when an external model is unavailable."""

    def __init__(self, primary, fallback: MockStructuredLLM) -> None:
        self.primary = primary
        self.fallback = fallback

    def parse(
        self,
        *,
        system_prompt: str,
        user_content: str,
        schema: type[SchemaT],
    ) -> SchemaT:
        try:
            return self.primary.parse(
                system_prompt=system_prompt,
                user_content=user_content,
                schema=schema,
            )
        except Exception as exc:
            logger.warning(
                "external LLM failed; using local deterministic fallback",
                extra={"schema": schema.__name__, "error_type": type(exc).__name__},
            )
            return self.fallback.parse(
                system_prompt=system_prompt,
                user_content=user_content,
                schema=schema,
            )


def build_llm(settings: Settings):
    provider = settings.llm_provider.lower()
    if provider == "mock":
        return MockStructuredLLM()
    if provider == "dashscope":
        return ResilientStructuredLLM(DashScopeStructuredLLM(settings), MockStructuredLLM())
    return ResilientStructuredLLM(OpenAIStructuredLLM(settings), MockStructuredLLM())


def _keywords(text: str, limit: int) -> list[str]:
    values = re.findall(r"[A-Za-z][A-Za-z0-9+#.-]{1,20}|[\u4e00-\u9fff]{2,8}", text)
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
        if len(result) >= limit:
            break
    return result or ["待进一步提取"]


def _mock_memory_candidates(message: str) -> list[MemoryCandidate]:
    patterns = [
        ("goal", r"(?:目标|想找|希望应聘|准备应聘)(?:是|：|:)?\s*([^，。；\n]{2,80})"),
        ("preference", r"(?:偏好|更喜欢|希望)(?:是|：|:)?\s*([^，。；\n]{2,80})"),
        ("experience", r"((?:有|具备)\s*\d+\s*年[^，。；\n]{1,80})"),
        ("constraint", r"((?:只能|不能|必须|限制)[^，。；\n]{1,80})"),
    ]
    result: list[MemoryCandidate] = []
    for category, pattern in patterns:
        match = re.search(pattern, message)
        if match:
            result.append(MemoryCandidate(category=category, content=match.group(1).strip()))
    return result[:5]


def _mock_coach_reply(payload: dict, message: str, memory_note: str) -> str:
    resume = payload.get("resume") or {}
    skills = resume.get("skills") or []
    skill_text = "、".join(skills[:6]) or "尚未提取到明确技能"
    jobs = payload.get("available_jobs") or []
    intent = (payload.get("deterministic_tool_context") or {}).get("intent")
    if intent == "job_recommendation" or any(
        word in message for word in ("岗位", "职位", "工作", "机会")
    ):
        if not jobs:
            return (
                f"{memory_note}我已读取你的最近简历，当前技能关键词是：{skill_text}。"
                "目前岗位库里还没有可比较的职位，请先在工作台添加一个或多个 JD；"
                "之后点击“推荐岗位”，我会直接给出优先级和匹配理由。"
            )
        lines = [
            f"{index}. {job['title']}｜{job['company']}｜{job.get('city') or '城市未注明'}"
            f"｜本地匹配 {job.get('match_score', 0)} 分"
            for index, job in enumerate(jobs[:5], start=1)
        ]
        return (
            f"{memory_note}我已自动读取你的最近简历（技能：{skill_text}），"
            f"并在岗位库中找到 {len(jobs)} 个可比较职位。\n\n"
            + "\n".join(lines)
            + "\n\n建议优先查看与上述技能直接重合的岗位，并补充项目规模、性能指标和个人贡献。"
            "这是基于当前已保存岗位的本地推荐；接入招聘平台后可扩展为实时岗位搜索。"
        )
    if intent == "resume_optimization" or "简历" in message:
        return (
            f"{memory_note}我已读取你的简历，识别到的技能包括：{skill_text}。"
            "优化时优先把每段项目改成“业务背景—个人行动—技术取舍—量化结果”，"
            "并把与目标岗位最相关的项目放在前面。点击或输入具体项目，我可以继续改写。"
        )
    if intent == "interview_preparation" or "面试" in message:
        return (
            f"{memory_note}我会基于你的简历技能（{skill_text}）开始准备。"
            "建议先练项目深挖，再练故障排查与系统设计；正式模拟可回到面试工作台，"
            "选择简历和岗位后直接生成 2～6 轮自适应问题。"
        )
    if intent == "gap_analysis":
        if jobs:
            top = jobs[0]
            matched = "、".join(top.get("matched_keywords") or []) or "暂无直接命中词"
            return (
                f"{memory_note}基于最近简历与当前岗位库，最接近的是“{top['title']}”，"
                f"本地匹配 {top.get('match_score', 0)} 分，命中：{matched}。"
                "建议先补齐 JD 中尚未在简历出现的硬技能，再补充项目规模、个人贡献和量化结果。"
            )
        return (
            f"{memory_note}我已读取你的简历（技能：{skill_text}），但岗位库为空，"
            "暂时无法做可信的差距对比。先添加一份目标 JD，再点击“分析差距”。"
        )
    if intent == "action_plan" or "计划" in message:
        return (
            f"{memory_note}7 天计划：第 1 天明确目标岗位；第 2 天整理技能证据；"
            "第 3 天改写简历项目；第 4 天准备高频技术题；第 5 天做项目深挖；"
            "第 6 天完成模拟面试；第 7 天复盘并投递。当前简历技能："
            f"{skill_text}。"
        )
    return (
        f"{memory_note}针对你刚才提到的“{message[:120]}”，我已经结合最近简历和对话上下文。"
        "你可以直接点击下方快捷按钮，让我推荐岗位、分析差距、优化简历或开始面试准备，"
        "不需要重新输入已有资料。"
    )

