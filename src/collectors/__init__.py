"""Collectors package exports."""

from src.collectors.contracts import CollectedDocument
from src.collectors.source_collector import (
    CollectStats,
    collect_documents_from_sources,
    collect_google_news_documents,
)

__all__ = [
    "CollectedDocument",
    "CollectStats",
    "collect_documents_from_sources",
    "collect_google_news_documents",
]
