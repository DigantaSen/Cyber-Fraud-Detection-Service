"""
Synthetic fraud-ring adjacency graphs for the Fraud Graph Analyzer (T9/T11).
3 labeled fraud-ring graphs + 2 benign (non-fraud) graphs, matching the
GraphAnalyzeRequest contract shape used by backend/ml-stubs/main.py.
"""

# Each entry: (name, anchorEntityId, nodes[], edges[], is_fraud_ring, expected_min_score)
GRAPH_CASES = [
    (
        "mule_ring_dense_hub",
        "+919876543210",
        [
            {"id": "+919876543210", "type": "PHONE", "fraudScore": 87},
            {"id": "+919876543211", "type": "PHONE", "fraudScore": 92},
            {"id": "+919876543212", "type": "PHONE", "fraudScore": 81},
            {"id": "ACC-9001", "type": "ACCOUNT", "fraudScore": 75},
            {"id": "ACC-9002", "type": "ACCOUNT", "fraudScore": 60},
        ],
        [
            {"from": "+919876543210", "to": "+919876543211", "relation": "CALLED", "count": 47},
            {"from": "+919876543210", "to": "+919876543212", "relation": "CALLED", "count": 12},
            {"from": "+919876543211", "to": "ACC-9001", "relation": "TRANSFERRED_TO", "count": 6},
            {"from": "+919876543212", "to": "ACC-9002", "relation": "TRANSFERRED_TO", "count": 5},
            {"from": "ACC-9001", "to": "ACC-9002", "relation": "LINKED", "count": 3},
        ],
        True,
        70,
    ),
    (
        "impersonation_call_chain",
        "+919812340000",
        [
            {"id": "+919812340000", "type": "PHONE", "fraudScore": 90},
            {"id": "+919812340001", "type": "PHONE", "fraudScore": 88},
            {"id": "+919812340002", "type": "PHONE", "fraudScore": 84},
            {"id": "+919812340003", "type": "PHONE", "fraudScore": 79},
        ],
        [
            {"from": "+919812340000", "to": "+919812340001", "relation": "CALLED", "count": 20},
            {"from": "+919812340001", "to": "+919812340002", "relation": "CALLED", "count": 18},
            {"from": "+919812340002", "to": "+919812340003", "relation": "CALLED", "count": 15},
            {"from": "+919812340000", "to": "+919812340003", "relation": "CALLED", "count": 9},
        ],
        True,
        60,
    ),
    (
        "upi_collector_hub",
        "ACC-5001",
        [
            {"id": "ACC-5001", "type": "ACCOUNT", "fraudScore": 95},
            {"id": "ACC-5002", "type": "ACCOUNT", "fraudScore": 30},
            {"id": "ACC-5003", "type": "ACCOUNT", "fraudScore": 25},
            {"id": "ACC-5004", "type": "ACCOUNT", "fraudScore": 40},
            {"id": "ACC-5005", "type": "ACCOUNT", "fraudScore": 88},
        ],
        [
            {"from": "ACC-5002", "to": "ACC-5001", "relation": "PAID", "count": 7},
            {"from": "ACC-5003", "to": "ACC-5001", "relation": "PAID", "count": 9},
            {"from": "ACC-5004", "to": "ACC-5001", "relation": "PAID", "count": 6},
            {"from": "ACC-5005", "to": "ACC-5001", "relation": "PAID", "count": 11},
        ],
        True,
        65,
    ),
    (
        "benign_family_contacts",
        "+919900000001",
        [
            {"id": "+919900000001", "type": "PHONE", "fraudScore": 5},
            {"id": "+919900000002", "type": "PHONE", "fraudScore": 2},
            {"id": "+919900000003", "type": "PHONE", "fraudScore": 3},
        ],
        [
            {"from": "+919900000001", "to": "+919900000002", "relation": "CALLED", "count": 4},
            {"from": "+919900000001", "to": "+919900000003", "relation": "CALLED", "count": 2},
        ],
        False,
        0,
    ),
    (
        "benign_sparse_merchant",
        "ACC-1000",
        [
            {"id": "ACC-1000", "type": "ACCOUNT", "fraudScore": 8},
            {"id": "ACC-1001", "type": "ACCOUNT", "fraudScore": 4},
        ],
        [
            {"from": "ACC-1001", "to": "ACC-1000", "relation": "PAID", "count": 1},
        ],
        False,
        0,
    ),
]
