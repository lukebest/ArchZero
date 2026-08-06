"""Clean-room / quantitative corpus scaffold (not a 95-paper claim)."""

from archzero.corpus.batch_eval import evaluate_corpus_batch
from archzero.corpus.ingest import add_paper_pdf
from archzero.corpus.status import corpus_status

__all__ = ["corpus_status", "add_paper_pdf", "evaluate_corpus_batch"]
