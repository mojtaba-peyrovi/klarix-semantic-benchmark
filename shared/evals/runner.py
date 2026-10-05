"""The eval runner (DEV_PLAN section 12.4).

CLI: uv run python -m shared.evals.runner --backend cube --provider gemini \
    --questions all --repeats 1

Runs every paraphrase of every selected golden question through one agent
(provider x backend), scores each with the deterministic scorers that apply to its
`kind` plus the LLM judge (always), scores cross-paraphrase consistency per
question, and writes runs/<timestamp>_<backend>_<provider>/{traces.jsonl,
scores.csv,report.md}.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime

import typer
from rich.console import Console

from shared.agent.loop import run_agent
from shared.agent.providers.anthropic_provider import AnthropicProvider
from shared.agent.providers.base import Provider
from shared.agent.providers.gemini_vertex import GeminiVertexProvider
from shared.backends.base import Backend
from shared.backends.naive_bigquery import NaiveBigQueryBackend
from shared.evals.golden_questions import GoldenQuestion, load_golden_questions
from shared.evals.judge import judge
from shared.evals.models import ParaphraseResult, QuestionResult
from shared.evals.report import build_report_md, to_csv_rows, write_csv
from shared.evals.scorers import (
    resolve_truth_ref,
    score_clarification,
    score_consistency,
    score_numeric,
)
from shared.settings import REPO_ROOT, Settings, load_settings
from shared.world.truth import ANSWERS_PATH

# Windows redirects stdout to cp1252 by default; LLM answer text routinely has
# characters it can't encode (see CLAUDE.md).
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

console = Console()

# Q17 is explicitly allowed to pass via stated assumptions instead of asking
# (DEV_PLAN 12.2's own carve-out).
_EXPLICIT_ASSUMPTIONS_OK = {"Q17"}


def _load_cube_backend(settings: Settings) -> Backend:
    path = REPO_ROOT / "project1-gcp-cube" / "backend" / "cube_backend.py"
    spec = importlib.util.spec_from_file_location("cube_backend", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.CubeBackend(settings)


def build_backend(name: str, settings: Settings) -> Backend:
    if name == "naive_bigquery":
        return NaiveBigQueryBackend(settings)
    if name == "cube":
        return _load_cube_backend(settings)
    raise ValueError(f"unknown backend {name!r}")


def build_provider(name: str, settings: Settings) -> Provider:
    if name == "gemini":
        return GeminiVertexProvider(
            model=settings.models.gemini,
            project=settings.gcp.project_id,
            location=settings.gcp.vertex_location,
        )
    if name == "anthropic":
        return AnthropicProvider(model=settings.models.anthropic_agent)
    raise ValueError(f"unknown provider {name!r}")


def run_question(
    question: GoldenQuestion,
    provider: Provider,
    backend: Backend,
    settings: Settings,
    answers: dict,
    repeats: int,
) -> QuestionResult:
    truth = resolve_truth_ref(answers, question.expected.truth_ref)
    allow_assumptions = question.id in _EXPLICIT_ASSUMPTIONS_OK

    paraphrase_results: list[ParaphraseResult] = []
    for idx, paraphrase in enumerate(question.paraphrases):
        for _ in range(repeats):
            run = run_agent(
                paraphrase, provider, backend, settings.benchmark.end_date, models=settings.models
            )

            numeric_score = None
            if question.expected.kind == "numeric":
                key_numbers = run.output.get("key_numbers") or []
                numeric_score = score_numeric(
                    key_numbers,
                    answers,
                    question.expected.truth_ref,
                    question.expected.tolerance_pct or 5.0,
                )

            clarification_score = None
            if question.expected.kind == "clarification":
                clarification_score = score_clarification(
                    run.terminal_tool, run.output, allow_explicit_assumptions=allow_assumptions
                )

            judge_result = judge(
                question=paraphrase,
                agent_output=run.output,
                rubric=question.rubric,
                truth=truth,
                model=settings.models.judge,
            )

            paraphrase_results.append(
                ParaphraseResult(
                    paraphrase_index=idx,
                    paraphrase=paraphrase,
                    agent_run=run,
                    numeric_score=numeric_score,
                    numeric_gates="P4" not in question.planted_problems(),
                    clarification_score=clarification_score,
                    judge_result=judge_result,
                )
            )
            console.print(
                f"  [{question.id}] paraphrase {idx}: "
                f"{'pass' if paraphrase_results[-1].passed else 'FAIL'}"
            )

    consistency_score = None
    if question.expected.kind in ("numeric", "table"):
        consistency_score = score_consistency([pr.agent_run.output for pr in paraphrase_results])

    return QuestionResult(
        question=question,
        paraphrase_results=paraphrase_results,
        consistency_score=consistency_score,
    )


def main(
    backend: str = typer.Option(..., help="naive_bigquery | cube"),
    provider: str = typer.Option(..., help="gemini | anthropic"),
    questions: str = typer.Option("all", help="'all' or a comma-separated list of ids (Q01,Q02)"),
    repeats: int = typer.Option(1, help="Times to repeat each paraphrase."),
) -> None:
    settings = load_settings()
    all_questions = load_golden_questions()
    if questions != "all":
        wanted = set(questions.split(","))
        all_questions = [q for q in all_questions if q.id in wanted]
        missing = wanted - {q.id for q in all_questions}
        if missing:
            raise SystemExit(f"unknown question ids: {sorted(missing)}")

    if not ANSWERS_PATH.exists():
        raise SystemExit("data/truth/answers.json missing; run `make world` first.")
    answers = json.loads(ANSWERS_PATH.read_text(encoding="utf-8"))

    backend_obj = build_backend(backend, settings)
    # One provider instance for the whole run: run_agent() calls provider.start()
    # at the top of every call, which resets its conversation state, so nothing
    # leaks between questions or paraphrases.
    provider_obj = build_provider(provider, settings)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = REPO_ROOT / "runs" / f"{timestamp}_{backend}_{provider}"
    out_dir.mkdir(parents=True, exist_ok=True)
    traces_path = out_dir / "traces.jsonl"

    results: list[QuestionResult] = []
    with traces_path.open("w", encoding="utf-8") as traces_file:
        for question in all_questions:
            console.rule(f"{question.id} ({question.category})")
            qr = run_question(question, provider_obj, backend_obj, settings, answers, repeats)
            results.append(qr)
            for pr in qr.paraphrase_results:
                traces_file.write(pr.agent_run.model_dump_json() + "\n")

    csv_rows = to_csv_rows(results)
    (out_dir / "scores.csv").write_text(write_csv(csv_rows), encoding="utf-8")

    model = settings.models.gemini if provider == "gemini" else settings.models.anthropic_agent
    report_md = build_report_md(results, backend, provider, model, timestamp)
    (out_dir / "report.md").write_text(report_md, encoding="utf-8")

    console.print(
        f"[green]Wrote {out_dir.relative_to(REPO_ROOT)}/{{traces.jsonl,scores.csv,report.md}}[/]"
    )
    overall_pass = sum(qr.passed for qr in results)
    console.print(f"Overall: {overall_pass}/{len(results)} questions passed")


if __name__ == "__main__":
    typer.run(main)
