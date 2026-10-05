"""Loads golden_questions.yaml (DEV_PLAN section 12.1) into typed models."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

GOLDEN_QUESTIONS_PATH = Path(__file__).resolve().parent / "golden_questions.yaml"

Category = Literal["straightforward", "definition", "trap", "ambiguous", "insight"]
Kind = Literal["numeric", "table", "clarification", "insight"]


class Expected(BaseModel):
    kind: Kind
    truth_ref: str
    tolerance_pct: float | None = None


class GoldenQuestion(BaseModel):
    id: str
    category: Category
    planted_problem: str | list[str] | None = None
    paraphrases: list[str] = Field(min_length=1)
    expected: Expected
    rubric: str

    def planted_problems(self) -> list[str]:
        if self.planted_problem is None:
            return []
        if isinstance(self.planted_problem, str):
            return [self.planted_problem]
        return self.planted_problem


def load_golden_questions(path: Path = GOLDEN_QUESTIONS_PATH) -> list[GoldenQuestion]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    questions = [GoldenQuestion.model_validate(q) for q in raw]
    ids = [q.id for q in questions]
    if len(ids) != len(set(ids)):
        dupes = {i for i in ids if ids.count(i) > 1}
        raise ValueError(f"golden_questions.yaml has duplicate ids: {dupes}")
    return questions
