from app.services.career_tools import classify_career_intent, rank_jobs


def test_career_intent_router_is_deterministic():
    assert classify_career_intent("帮我推荐适合的岗位") == "job_recommendation"
    assert classify_career_intent("优化一下我的项目经历") == "resume_optimization"
    assert classify_career_intent("我和目标职位还有什么差距") == "gap_analysis"
    assert classify_career_intent("给我一个七天行动计划") == "action_plan"


def test_rank_jobs_uses_resume_and_returns_explainable_evidence():
    resume = {"skills": ["Python", "FastAPI", "MySQL"], "projects": ["智能求职 Agent"]}
    jobs = [
        {
            "id": "backend",
            "title": "Python 后端工程师",
            "company": "示例公司",
            "city": "深圳",
            "description": "使用 Python、FastAPI 和 MySQL 开发服务",
        },
        {
            "id": "designer",
            "title": "视觉设计师",
            "company": "示例公司",
            "city": "上海",
            "description": "负责品牌和视觉设计",
        },
    ]

    ranked = rank_jobs(resume, jobs)

    assert ranked[0]["id"] == "backend"
    assert ranked[0]["match_score"] > ranked[1]["match_score"]
    assert {"python", "fastapi", "mysql"}.issubset(set(ranked[0]["matched_keywords"]))
