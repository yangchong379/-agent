from app.schemas.domain import ScoreDimensions


def dimension_total(dimensions: ScoreDimensions) -> int:
    return sum(
        (
            dimensions.relevance,
            dimensions.correctness,
            dimensions.depth,
            dimensions.engineering,
            dimensions.communication,
        )
    )


def final_score(initial_score: int, followup_score: int) -> int:
    initial = max(0, min(100, initial_score))
    followup = max(0, min(100, followup_score))
    return round(initial * 0.75 + followup * 0.25)

