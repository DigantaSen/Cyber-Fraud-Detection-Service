import json
import uuid
import logging
import asyncio
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from fastapi import APIRouter, Request, BackgroundTasks
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse
from pydantic import BaseModel
import httpx

from config import settings
from response_helpers import success_response, error_response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/notify", tags=["Notification"])


class NotificationRequest(BaseModel):
    userId: str
    channel: str
    templateId: str
    variables: Dict[str, Any]
    priority: str = "NORMAL"


class MHAAlertRequest(BaseModel):
    caseId: str
    alertType: str
    riskTier: str
    summary: str
    suspects: list[str]
    jurisdictionId: str
    triggeredBy: str


class PreferencesUpdate(BaseModel):
    smsEnabled: Optional[bool] = None
    emailEnabled: Optional[bool] = None
    pushEnabled: Optional[bool] = None
    quietHoursStart: Optional[str] = None
    quietHoursEnd: Optional[str] = None
    language: Optional[str] = None


def publish_event(producer, topic: str, event_type: str, data: dict, correlation_id: str):
    payload = {
        "eventId": str(uuid.uuid4()),
        "eventType": event_type,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "correlationId": correlation_id,
        "data": data
    }
    producer.produce(topic, value=json.dumps(payload).encode('utf-8'))
    producer.poll(0)


@router.post("/send")
async def send_notification(
    request: Request,
    payload: NotificationRequest,
    background_tasks: BackgroundTasks
):
    correlation_id = request.headers.get("X-Correlation-ID", "")
    notification_id = str(uuid.uuid4())
    
    # Stub logic - logs to console
    logger.info(f"[STUB {payload.channel}] Sending {payload.templateId} to {payload.userId}. Priority: {payload.priority}")
    
    # Publish Notification.Requested
    producer = request.app.state.kafka_producer
    publish_event(producer, "Notification.Requested", "Notification.Requested", {
        "notificationId": notification_id,
        "userId": payload.userId,
        "channel": payload.channel,
        "priority": payload.priority
    }, correlation_id)
    
    return JSONResponse(status_code=202, content=success_response({
        "notificationId": notification_id,
        "status": "QUEUED",
        "estimatedDeliveryMs": 500
    }, correlation_id))


@router.post("/mha-alert")
async def send_mha_alert(
    request: Request,
    payload: MHAAlertRequest
):
    correlation_id = request.headers.get("X-Correlation-ID", "")
    alert_id = str(uuid.uuid4())
    
    http_client: httpx.AsyncClient = request.app.state.http_client
    producer = request.app.state.kafka_producer
    
    start_time = asyncio.get_event_loop().time()
    
    try:
        # Webhook POST to MHA endpoint
        resp = await http_client.post(
            settings.MHA_WEBHOOK_URL,
            json=payload.model_dump(),
            headers={"X-Correlation-ID": correlation_id},
            timeout=4.0
        )
        # We ignore resp.status_code for now or log it
        logger.info(f"MHA webhook response: {resp.status_code}")
    except Exception as e:
        logger.error(f"Failed to post to MHA webhook: {e}")
        # In a real system, we might retry or queue. For <5s SLO we do our best.

    end_time = asyncio.get_event_loop().time()
    latency_ms = int((end_time - start_time) * 1000)
    
    # Publish MHAAlert.Sent
    publish_event(producer, "MHAAlert.Sent", "MHAAlert.Sent", {
        "alertId": alert_id,
        "caseId": payload.caseId,
        "alertType": payload.alertType,
        "jurisdictionId": payload.jurisdictionId,
        "latencyMs": latency_ms
    }, correlation_id)

    return success_response({
        "alertId": alert_id,
        "status": "DISPATCHED",
        "dispatchedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "deliveryLatencyMs": latency_ms
    }, correlation_id)


@router.get("/stream")
async def sse_stream(request: Request):
    """
    Server-Sent Events stream for real-time investigator dashboard updates.
    """
    # X-User-Context would have the user info to scope events
    # For now, we subscribe to a global Redis pubsub channel or user-specific channel
    redis_client = request.app.state.redis
    
    async def event_generator():
        pubsub = redis_client.pubsub()
        await pubsub.subscribe("investigator_sse_events")
        
        try:
            while True:
                if await request.is_disconnected():
                    break
                
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message is not None:
                    # message data should be a json string with "event" and "data" keys
                    try:
                        data = json.loads(message["data"])
                        yield {
                            "event": data.get("event", "message"),
                            "data": json.dumps(data.get("data", {}))
                        }
                    except Exception as e:
                        logger.error(f"Error parsing pubsub message: {e}")
        finally:
            await pubsub.unsubscribe("investigator_sse_events")
            
    return EventSourceResponse(event_generator())


@router.get("/preferences/{userId}")
async def get_preferences(request: Request, userId: str):
    correlation_id = request.headers.get("X-Correlation-ID", "")
    redis_client = request.app.state.redis
    
    key = f"notify:prefs:{userId}"
    data = await redis_client.hgetall(key)
    
    if not data:
        # Return defaults
        data = {
            "smsEnabled": "1",
            "emailEnabled": "1",
            "pushEnabled": "0",
            "quietHoursStart": "22:00",
            "quietHoursEnd": "07:00",
            "language": "hi"
        }
    
    return success_response({
        "userId": userId,
        "smsEnabled": data.get("smsEnabled") == "1",
        "emailEnabled": data.get("emailEnabled") == "1",
        "pushEnabled": data.get("pushEnabled") == "1",
        "quietHoursStart": data.get("quietHoursStart", "22:00"),
        "quietHoursEnd": data.get("quietHoursEnd", "07:00"),
        "language": data.get("language", "hi")
    }, correlation_id)


@router.patch("/preferences/{userId}")
async def update_preferences(request: Request, userId: str, payload: PreferencesUpdate):
    correlation_id = request.headers.get("X-Correlation-ID", "")
    redis_client = request.app.state.redis
    
    key = f"notify:prefs:{userId}"
    updates = {}
    if payload.smsEnabled is not None:
        updates["smsEnabled"] = "1" if payload.smsEnabled else "0"
    if payload.emailEnabled is not None:
        updates["emailEnabled"] = "1" if payload.emailEnabled else "0"
    if payload.pushEnabled is not None:
        updates["pushEnabled"] = "1" if payload.pushEnabled else "0"
    if payload.quietHoursStart is not None:
        updates["quietHoursStart"] = payload.quietHoursStart
    if payload.quietHoursEnd is not None:
        updates["quietHoursEnd"] = payload.quietHoursEnd
    if payload.language is not None:
        updates["language"] = payload.language
        
    if updates:
        await redis_client.hset(key, mapping=updates)
        
    return await get_preferences(request, userId)
