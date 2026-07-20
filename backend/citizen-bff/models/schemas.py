"""Pydantic schemas for Citizen BFF API."""
import uuid
from typing import Optional
from pydantic import BaseModel

class CurrentUser(BaseModel):
    """Decoded JWT claims. Passed via Depends(get_current_user)."""
    user_id: uuid.UUID
    email: str
    role: str
    org_id: Optional[uuid.UUID] = None
    jurisdiction_id: Optional[str] = None
    jti: str  # JWT ID — used for denylist check
