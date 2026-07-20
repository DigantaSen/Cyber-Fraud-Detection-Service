import httpx
from fastapi import Request

def get_case_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.case_client

def get_search_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.search_client

def get_geo_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.geo_client

def get_graph_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.graph_client

def get_evidence_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.evidence_client

def get_reporting_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.reporting_client

def get_notification_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.notification_client
