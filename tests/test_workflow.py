from pathlib import Path

from app.llm.providers import MockStructuredLLM, ResilientStructuredLLM
from app.schemas.domain import CareerCoachReply
from app.services.retrieval import LocalKnowledgeRetriever
from app.workflows.interview import build_preparation_graph, create_final_report, evaluate_answer


def test_workflow_and_score_control():
    llm = MockStructuredLLM()
    graph = build_preparation_graph(llm, LocalKnowledgeRetriever(Path("knowledge")))
    state = graph.invoke(
        {
            "resume_text": "Java 开发工程师，负责 Spring Boot、MySQL 和 Redis 性能优化项目。",
            "jd_text": "招聘 Java 后端工程师，要求分布式系统、数据库调优和故障排查经验。",
        }
    )
    assert state["question"]["question"]
    evaluation = evaluate_answer(
        llm,
        state["question"],
        "我先建立延迟与吞吐基线，再通过 GC 日志和火焰图定位，最后用压测验证。",
        state["evidence"],
    )
    report = create_final_report(llm, evaluation, evaluation)
    assert evaluation.total_score == sum(evaluation.dimensions.model_dump().values())
    assert report.final_score == evaluation.total_score


def test_external_model_failure_uses_local_fallback():
    class BrokenProvider:
        def parse(self, **kwargs):
            del kwargs
            raise ConnectionError("provider unavailable")

    llm = ResilientStructuredLLM(BrokenProvider(), MockStructuredLLM())
    result = llm.parse(
        system_prompt="coach",
        user_content=(
            '{"current_user_message":"帮我制定计划","resume":{},'
            '"deterministic_tool_context":{"intent":"action_plan"}}'
        ),
        schema=CareerCoachReply,
    )

    assert "7 天计划" in result.reply

