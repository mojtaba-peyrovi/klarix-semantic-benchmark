"""Result types shared between runner.py (produces them) and report.py (reads
them) -- kept separate from both so neither module has to import the other.
"""

from __future__ import annotations

from pydantic import BaseModel

from shared.agent.loop import AgentRun
from shared.evals.golden_questions import GoldenQuestion
from shared.evals.judge import JudgeResult
from shared.evals.scorers import ClarificationScore, ConsistencyScore, NumericScore


class ParaphraseResult(BaseModel):
    paraphrase_index: int
    paraphrase: str
    agent_run: AgentRun
    numeric_score: NumericScore | None = None
    # Whether numeric_score.passed gates overall pass/fail, or is recorded for the
    # report but left to the judge. False for P4-tagged numeric questions: P4's
    # internal/test accounts structurally can't be excluded on an ungoverned
    # backend, so those numbers are EXPECTED to run off-truth there (see Q01/Q04/
    # Q05/Q07/Q14's rubrics) -- a naive numeric gate would fail an agent for
    # correctly reporting the polluted number AND flagging why, which is exactly
    # the behavior those questions are designed to reward. Set by the runner (it
    # knows the question, this model doesn't import golden_questions to decide).
    numeric_gates: bool = True
    clarification_score: ClarificationScore | None = None
    judge_result: JudgeResult

    @property
    def passed(self) -> bool:
        checks = [self.judge_result.passed]
        if self.numeric_score is not None and self.numeric_gates:
            checks.append(self.numeric_score.passed)
        if self.clarification_score is not None:
            checks.append(self.clarification_score.passed)
        return all(checks)


class QuestionResult(BaseModel):
    question: GoldenQuestion
    paraphrase_results: list[ParaphraseResult]
    consistency_score: ConsistencyScore | None = None

    @property
    def passed(self) -> bool:
        base = all(p.passed for p in self.paraphrase_results)
        if self.consistency_score is not None:
            base = base and self.consistency_score.passed
        return base
