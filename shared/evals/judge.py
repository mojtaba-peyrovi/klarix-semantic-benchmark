"""The LLM judge (DEV_PLAN section 12.3): one fixed Claude model (config/
settings.yaml's models.judge) grades an agent's final output against a question's
rubric, returning {pass, reason}. Cached by a hash of (model, question, rubric,
agent output, ground truth) -- re-running a report never re-spends judge tokens on
an identical case, and a changed rubric or a reseeded dataset naturally busts the
cache since the hash changes.

The rubric text may describe the correct answer in words (see golden_questions.yaml),
but the judge is also given the actual resolved truth_ref value as JSON, since that's
the authoritative source -- the rubric's prose is a human-readable aid, not the
thing being graded against.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import anthropic
from pydantic import BaseModel

from shared.settings import REPO_ROOT

CACHE_DIR = REPO_ROOT / "runs" / ".judge_cache"

JUDGE_SYSTEM_PROMPT = """\
You are grading an AI analyst's answer to a business question against a rubric. \
You are given the question, the analyst's full final output (JSON), the rubric, \
and the actual ground-truth data the rubric refers to.

Call the submit_verdict tool with your verdict.

Be strict: an answer that sounds plausible but misses what the rubric specifically \
requires (a stated definition, a caveat, correctly identifying the real driver \
rather than a superficially similar wrong one) should fail.
"""

# Forcing the verdict through a tool call (instead of asking the model to free-text
# a JSON blob) guarantees parseable output -- found live: a free-text "reason" with
# an unescaped quote inside it broke json.loads mid-run and crashed the whole eval
# (JSONDecodeError, "Expecting ',' delimiter"), discarding every question already
# scored in that run.
_VERDICT_TOOL = {
    "name": "submit_verdict",
    "description": "Submit the grading verdict.",
    "input_schema": {
        "type": "object",
        "properties": {
            "pass": {"type": "boolean"},
            "reason": {"type": "string", "description": "One or two sentences."},
        },
        "required": ["pass", "reason"],
    },
}


class JudgeResult(BaseModel):
    passed: bool
    reason: str


def _cache_key(model: str, question: str, rubric: str, output_json: str, truth_json: str) -> str:
    h = hashlib.sha256()
    for part in (model, question, rubric, output_json, truth_json):
        h.update(part.encode("utf-8"))
        h.update(b"\0")
    return h.hexdigest()


def judge(
    question: str,
    agent_output: dict[str, Any],
    rubric: str,
    truth: Any,
    model: str,
    client: anthropic.Anthropic | None = None,
) -> JudgeResult:
    output_json = json.dumps(agent_output, sort_keys=True, default=str)
    truth_json = json.dumps(truth, sort_keys=True, default=str)
    key = _cache_key(model, question, rubric, output_json, truth_json)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = CACHE_DIR / f"{key}.json"
    if cache_path.exists():
        return JudgeResult.model_validate_json(cache_path.read_text(encoding="utf-8"))

    client = client or anthropic.Anthropic()
    user_message = (
        f"Question asked: {question}\n\n"
        f"Analyst's final output (JSON):\n{output_json}\n\n"
        f"Rubric:\n{rubric}\n\n"
        f"Ground truth data (JSON):\n{truth_json}"
    )
    response = client.messages.create(
        model=model,
        # claude-opus-5 thinks by default (adaptive) even without a `thinking`
        # param; 300 max_tokens was too small to hold thinking + the JSON verdict
        # and truncated mid-string (found live). effort="low" keeps thinking short
        # for a task this simple -- grading is not worth spending reasoning on.
        max_tokens=1024,
        output_config={"effort": "low"},
        system=JUDGE_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
        tools=[_VERDICT_TOOL],
        tool_choice={"type": "tool", "name": "submit_verdict"},
    )
    tool_use = next(block for block in response.content if block.type == "tool_use")
    result = JudgeResult(passed=bool(tool_use.input["pass"]), reason=str(tool_use.input["reason"]))
    cache_path.write_text(result.model_dump_json(), encoding="utf-8")
    return result
