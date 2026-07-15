"""
Bot Session Service — Redis-backed multi-turn conversation state.
Key pattern: bot:session:{sessionId}:lang={lang_code}  (from docs/db/redis.md)
TTL: 1800 seconds (30 min), refreshed on every message.

Session data structure:
{
    "sessionId": "uuid",
    "turnCount": 3,
    "detectedLanguage": "hi",
    "messages": [{"role": "user"|"bot", "content": "...", "ts": "iso"}],
    "collectedData": {"suspectPhone": "...", "complaintType": "..."},
    "status": "ACTIVE",
    "channel": "WEB",
    "userId": "uuid or null"
}
"""
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import redis.asyncio as aioredis

_SESSION_TTL = 1800   # 30 minutes (docs/db/redis.md)


class SessionService:

    def __init__(self, redis: aioredis.Redis):
        self._redis = redis

    def _make_key(self, session_id: str, lang_code: str) -> str:
        """Build Redis key: bot:session:{sessionId}:lang={lang_code}"""
        return f"bot:session:{session_id}:lang={lang_code}"

    def _scan_key_pattern(self, session_id: str) -> str:
        """
        Pattern for scanning when lang_code is unknown.
        Assumption: scan_iter is acceptable for hackathon scale (low session count).
        Production would use a secondary index or a fixed key with no lang in the name.
        """
        return f"bot:session:{session_id}:lang=*"

    async def get_session(self, session_id: str) -> Optional[dict]:
        """
        Retrieve session by session_id.
        Scans for the key since lang_code may vary.
        Returns None if not found or expired.
        """
        pattern = self._scan_key_pattern(session_id)
        keys = []
        async for key in self._redis.scan_iter(pattern):
            keys.append(key)
        
        if not keys:
            return None
        
        # Take the first matching key (should only be one per session)
        data = await self._redis.get(keys[0])
        return json.loads(data) if data else None

    async def create_session(
        self,
        lang_code: str,
        channel: str,
        user_id: Optional[str],
        first_message: str,
    ) -> dict:
        """Create a new session and store in Redis."""
        session_id = str(uuid.uuid4())
        expires_at = (datetime.now(timezone.utc) + timedelta(seconds=_SESSION_TTL)).isoformat()
        
        state = {
            "sessionId": session_id,
            "turnCount": 1,
            "detectedLanguage": lang_code,
            "messages": [
                {"role": "user", "content": first_message, "ts": datetime.now(timezone.utc).isoformat()}
            ],
            "collectedData": {},
            "status": "ACTIVE",
            "channel": channel,
            "userId": user_id,
            "expiresAt": expires_at,
        }
        
        key = self._make_key(session_id, lang_code)
        await self._redis.setex(key, _SESSION_TTL, json.dumps(state))
        return state

    async def update_session(
        self,
        session_id: str,
        lang_code: str,
        user_message: str,
        bot_response: str,
        collected_data_update: Optional[dict] = None,
    ) -> dict:
        """Append turn to session and refresh TTL."""
        state = await self.get_session(session_id)
        if not state:
            raise SessionNotFoundError(session_id)

        now = datetime.now(timezone.utc).isoformat()
        state["turnCount"] += 1
        state["detectedLanguage"] = lang_code
        state["messages"].extend([
            {"role": "user", "content": user_message, "ts": now},
            {"role": "bot", "content": bot_response, "ts": now},
        ])
        if collected_data_update:
            state["collectedData"].update(collected_data_update)
        state["expiresAt"] = (datetime.now(timezone.utc) + timedelta(seconds=_SESSION_TTL)).isoformat()

        # Delete old key (lang_code may have changed) and write new
        old_pattern = self._scan_key_pattern(session_id)
        async for old_key in self._redis.scan_iter(old_pattern):
            await self._redis.delete(old_key)

        new_key = self._make_key(session_id, lang_code)
        await self._redis.setex(new_key, _SESSION_TTL, json.dumps(state))
        return state

    async def delete_session(self, session_id: str) -> None:
        async for key in self._redis.scan_iter(self._scan_key_pattern(session_id)):
            await self._redis.delete(key)


class SessionNotFoundError(Exception):
    def __init__(self, session_id: str):
        super().__init__(f"Session {session_id} not found or expired")
