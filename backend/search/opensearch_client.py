"""
Search Service — OpenSearch Client Singleton

Manages the connection to OpenSearch and handles index creation.
Index mappings are taken directly from docs/db/opensearch.json.
"""

import logging
from opensearchpy import OpenSearch, NotFoundError

from config import settings

logger = logging.getLogger("opensearch-client")

# ── Index Mappings (from docs/db/opensearch.json) ─────────────────────────────

CASE_INDEX_BODY = {
    "settings": {
        "number_of_shards": 1,
        "number_of_replicas": 0
    },
    "mappings": {
        "dynamic": "false",
        "properties": {
            "caseId":               {"type": "keyword"},
            "caseNumber":           {"type": "keyword"},
            "title":                {"type": "text"},
            "description":          {"type": "text", "analyzer": "standard"},
            "notes":                {"type": "text", "analyzer": "standard"},
            "status":               {"type": "keyword"},
            "riskTier":             {"type": "keyword"},
            "confidence":           {"type": "float"},
            "fusedScore":           {"type": "float"},
            "jurisdictionId":       {"type": "keyword"},
            "assignedInvestigator": {"type": "keyword"},
            "complaintType":        {"type": "keyword"},
            "reporterPhone":        {"type": "keyword"},
            "complaintLocation":    {"type": "geo_point"},
            "reporterEntityName": {
                "type": "text",
                "fields": {
                    "keyword": {"type": "keyword"}
                }
            },
            "createdAt": {"type": "date"},
            "updatedAt": {"type": "date"}
        }
    }
}

EVIDENCE_INDEX_BODY = {
    "settings": {
        "number_of_shards": 1,
        "number_of_replicas": 0
    },
    "mappings": {
        "dynamic": "false",
        "properties": {
            "evidenceId":  {"type": "keyword"},
            "caseId":      {"type": "keyword"},
            "fileName":    {"type": "text"},
            "mimeType":    {"type": "keyword"},
            "sha256":      {"type": "keyword"},
            "fileSize":    {"type": "long"},
            "uploadedBy":  {"type": "keyword"},
            "createdAt":   {"type": "date"}
        }
    }
}

# ── Client Singleton ───────────────────────────────────────────────────────────

def create_client() -> OpenSearch:
    """Create and return an OpenSearch client."""
    return OpenSearch(
        hosts=[settings.OPENSEARCH_URL],
        use_ssl=False,
        verify_certs=False,
        http_compress=True,
    )

# Module-level client instance
client = create_client()


def ensure_indices():
    """
    Create case_index and evidence_index if they do not already exist.
    Called on startup of both the API server and the consumer pod.
    """
    indices = {
        "case_index":     CASE_INDEX_BODY,
        "evidence_index": EVIDENCE_INDEX_BODY,
    }
    for index_name, body in indices.items():
        if not client.indices.exists(index=index_name):
            logger.info(f"Creating OpenSearch index: {index_name}")
            client.indices.create(index=index_name, body=body)
        else:
            logger.info(f"OpenSearch index already exists: {index_name}")
