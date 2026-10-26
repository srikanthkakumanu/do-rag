"""Offline quality gate: run the golden set through retrieval + generation.

Needs a running Weaviate with the corpus ingested and a valid OpenAI key in advanced/.env.
Usage: uv run python -m eval.run [--report eval/reports/<date>.json]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Final

from advanced.config import get_settings
from advanced.domain import CardNetwork, Turn
from advanced.generation.llm import OpenAIAnswerer
from advanced.ingestion.scrub import scrub
from advanced.llm import OpenAIStructuredLLM, make_openai_client
from advanced.query.planner import LLMQueryPlanner
from advanced.rag import AdvancedRag
from advanced.retrieval.reranker import LLMReranker
from advanced.retrieval.retriever import WeaviateRetriever, WeaviateSectionStore
from advanced.vectordb import make_async

GOLDEN: Final = Path(__file__).parent / "golden.jsonl"
THRESHOLDS: Final = {
    "recall_at_5": 0.90,
    "citation_accuracy": 0.95,
    "refusal_precision": 0.95,
    "refusal_recall": 0.95,
}
P95_LATENCY_MS: Final = 6000.0  # plan + rerank + answer: three LLM calls


@dataclass(frozen=True, slots=True)
class GoldenItem:
    question: str
    expected_doc_ids: tuple[str, ...]
    must_refuse: bool
    card_network: CardNetwork | None = None
    history: tuple[Turn, ...] = ()


@dataclass(frozen=True, slots=True)
class Outcome:
    item: GoldenItem
    retrieved_doc_ids: tuple[str, ...]
    cited_doc_ids: tuple[str, ...]
    refused: bool
    latency_ms: float


def load_golden(path: Path = GOLDEN) -> list[GoldenItem]:
    items: list[GoldenItem] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            net = row.get("card_network")
            items.append(
                GoldenItem(
                    question=row["question"],
                    expected_doc_ids=tuple(row["expected_doc_ids"]),
                    must_refuse=bool(row["must_refuse"]),
                    card_network=CardNetwork(net) if net else None,
                    history=tuple(Turn(**t) for t in row.get("history", [])),
                )
            )
    return items


def _ratio(num: int, den: int) -> float:
    return num / den if den else 1.0


def compute_metrics(outcomes: list[Outcome]) -> dict[str, float]:
    """recall@5, citation accuracy, refusal precision/recall, p95 latency."""
    answerable = [o for o in outcomes if not o.item.must_refuse]
    hits = sum(1 for o in answerable if set(o.item.expected_doc_ids) & set(o.retrieved_doc_ids))
    cited = [d for o in answerable if not o.refused for d in o.cited_doc_ids]
    correct_cites = sum(
        1
        for o in answerable
        if not o.refused
        for d in o.cited_doc_ids
        if d in o.item.expected_doc_ids
    )
    refused = [o for o in outcomes if o.refused]
    should = [o for o in outcomes if o.item.must_refuse]
    latencies = sorted(o.latency_ms for o in outcomes)
    p95 = (
        statistics.quantiles(latencies, n=20)[18]
        if len(latencies) >= 2
        else (latencies[0] if latencies else 0.0)
    )
    return {
        "recall_at_5": _ratio(hits, len(answerable)),
        "citation_accuracy": _ratio(correct_cites, len(cited)),
        "refusal_precision": _ratio(sum(o.item.must_refuse for o in refused), len(refused)),
        "refusal_recall": _ratio(sum(o.refused for o in should), len(should)),
        "answer_rate": _ratio(sum(not o.refused for o in answerable), len(answerable)),
        "p95_latency_ms": round(p95, 1),
    }


def gate(metrics: dict[str, float]) -> list[str]:
    """Return the names of failed thresholds (empty = pass)."""
    failed = [k for k, v in THRESHOLDS.items() if metrics[k] < v]
    if metrics["p95_latency_ms"] >= P95_LATENCY_MS:
        failed.append("p95_latency_ms")
    return failed


async def _run(items: list[GoldenItem]) -> list[Outcome]:
    settings = get_settings()
    client = make_async(settings)
    await client.connect()
    openai_client = make_openai_client(settings)
    llm = OpenAIStructuredLLM(openai_client, settings)
    rag = AdvancedRag(
        planner=LLMQueryPlanner(llm, settings),
        retriever=WeaviateRetriever(client, settings),
        sections=WeaviateSectionStore(client, settings),
        reranker=LLMReranker(llm, settings),
        answerer=OpenAIAnswerer(llm, settings),
        settings=settings,
    )
    try:
        outcomes: list[Outcome] = []
        for item in items:
            started = time.perf_counter()
            history = [Turn(role=t.role, content=scrub(t.content).clean_text) for t in item.history]
            result = await rag.answer(
                scrub(item.question).clean_text,
                history,
                card_network=item.card_network,
                as_of=date.today(),
            )
            outcomes.append(
                Outcome(
                    item=item,
                    retrieved_doc_ids=tuple(result.candidate_doc_ids[:5]),
                    cited_doc_ids=tuple(c.doc_id for c in result.answer.citations),
                    refused=result.answer.refused,
                    latency_ms=(time.perf_counter() - started) * 1000,
                )
            )
        return outcomes
    finally:
        await client.close()
        await openai_client.close()


def main() -> int:
    parser = argparse.ArgumentParser(prog="eval.run")
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args()
    outcomes = asyncio.run(_run(load_golden()))
    metrics = compute_metrics(outcomes)
    failed = gate(metrics)
    report = {
        "date": date.today().isoformat(),
        "prompt_version": get_settings().prompt_version,
        "metrics": metrics,
        "thresholds": THRESHOLDS | {"p95_latency_ms_max": P95_LATENCY_MS},
        "passed": not failed,
        "failed": failed,
        "misses": [
            {"question": o.item.question, "expected_doc_ids": o.item.expected_doc_ids}
            | {"retrieved": o.retrieved_doc_ids, "refused": o.refused}
            for o in outcomes
            if o.refused != o.item.must_refuse
            or (
                not o.item.must_refuse
                and not set(o.item.expected_doc_ids) & set(o.retrieved_doc_ids)
            )
        ],
    }
    text = json.dumps(report, indent=2, default=str)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text, encoding="utf-8")
    print(text)  # noqa: T201
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
