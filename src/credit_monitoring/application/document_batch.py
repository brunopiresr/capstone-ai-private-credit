"""Bounded document workers with ordered outcomes and caller-thread progress."""

import logging
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextvars import copy_context
from dataclasses import dataclass
from queue import Empty, Queue
from time import perf_counter

from credit_monitoring.domain.processing import DocumentExtraction
from credit_monitoring.ingestion.loaders.sec import filing_citation

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DocumentBatchProgress:
    document_id: str
    document_index: int
    total_documents: int
    stage: str
    completed_sections: int
    total_sections: int
    completed_documents: int
    total_fraction: float
    outcome: DocumentExtraction | None = None


def validate_workers(max_workers: int) -> None:
    if isinstance(max_workers, bool) or not isinstance(max_workers, int) or max_workers < 1:
        raise ValueError("max_workers must be a positive integer.")


def run_document_batch(
    records: list[dict],
    process: Callable,
    *,
    max_workers: int,
    progress: Callable[[DocumentBatchProgress], None] | None = None,
) -> list[DocumentExtraction]:
    """Drain worker events on the caller; completion order never changes result order."""
    validate_workers(max_workers)
    total, started = len(records), perf_counter()
    fractions = [0.0] * total
    completed = set()
    events = Queue()
    outcomes: dict[int, DocumentExtraction] = {}

    def emit(index, stage, done=0, sections=0, outcome=None):
        fraction = done / sections if sections else 0.0
        if outcome is not None:
            completed.add(index)
            fraction = 1.0
        fractions[index] = max(fractions[index], min(1.0, fraction))
        if progress:
            progress(
                DocumentBatchProgress(
                    records[index]["document_id"],
                    index + 1,
                    total,
                    stage,
                    done,
                    sections,
                    len(completed),
                    sum(fractions) / total,
                    outcome,
                )
            )

    def one(index, record, report):
        begin = perf_counter()
        document_id = record["document_id"]
        logger.info(
            "Batch document started document=%d/%d document_id=%s ticker=%s",
            index + 1,
            total,
            document_id,
            record.get("ticker"),
        )
        try:
            outcome = process(record, report)
        except Exception as exc:
            logger.error(
                "Batch document failed",
                extra={
                    "document_id": document_id,
                    "error_type": type(exc).__name__,
                },
            )
            outcome = DocumentExtraction(
                document_id=document_id,
                citation=filing_citation(record),
                ticker=record.get("ticker") or None,
                status="failed",
                error=f"{type(exc).__name__}: {exc}",
            )
        logger.log(
            logging.ERROR if outcome.status == "failed" else logging.INFO,
            "Batch document finished document=%d/%d document_id=%s status=%s "
            "cache_hit=%s elapsed_s=%.2f",
            index + 1,
            total,
            document_id,
            outcome.status,
            outcome.cache_hit,
            perf_counter() - begin,
        )
        return outcome

    def finish(index, outcome):
        outcomes[index] = outcome
        emit(
            index,
            "Failed" if outcome.status == "failed" else "Finished",
            outcome.completed_sections,
            outcome.total_sections,
            outcome,
        )

    logger.info("Batch ready total_documents=%d workers=%d", total, min(max_workers, total))
    if max_workers == 1 or total < 2:
        for index, record in enumerate(records):
            finish(
                index,
                one(
                    index,
                    record,
                    lambda stage, done, sections, i=index: emit(i, stage, done, sections),
                ),
            )
    else:
        with ThreadPoolExecutor(
            max_workers=min(max_workers, total), thread_name_prefix="credit-document"
        ) as executor:
            pending = {}
            for index, record in enumerate(records):

                def report(stage, done, sections, i=index):
                    events.put((i, stage, done, sections))

                future = executor.submit(copy_context().run, one, index, record, report)
                pending[future] = index
            while pending:
                ready, _ = wait(pending, timeout=0.05, return_when=FIRST_COMPLETED)
                while True:
                    try:
                        emit(*events.get_nowait())
                    except Empty:
                        break
                for future in ready:
                    finish(pending.pop(future), future.result())
    ordered = [outcomes[index] for index in range(total)]
    logger.info(
        "Batch summary total_documents=%d completed=%d failed=%d cache_hits=%d "
        "workers=%d elapsed_s=%.2f",
        total,
        sum(r.status == "complete" for r in ordered),
        sum(r.status == "failed" for r in ordered),
        sum(r.cache_hit for r in ordered),
        min(max_workers, total),
        perf_counter() - started,
    )
    return ordered
