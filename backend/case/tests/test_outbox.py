"""Unit tests for outbox write pattern (case + outbox in same transaction)."""
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch, call

import pytest

from repositories.outbox_repository import OutboxRepository


class TestOutboxRepository:

    @pytest.mark.asyncio
    async def test_publish_inserts_outbox_row(self):
        """OutboxRepository.publish should add a row to the session."""
        mock_session = AsyncMock()
        mock_session.flush = AsyncMock()
        
        repo = OutboxRepository(mock_session)
        case_id = uuid.uuid4()
        
        await repo.publish(
            aggregate_type="Case",
            aggregate_id=case_id,
            event_type="Case.Created",
            topic="case.created",
            event_key=str(case_id),
            payload={"caseId": str(case_id)},
        )
        
        # Verify session.add was called
        mock_session.add.assert_called_once()
        added_obj = mock_session.add.call_args[0][0]
        assert added_obj.event_type == "Case.Created"
        assert added_obj.topic == "case.created"
        assert added_obj.aggregate_type == "Case"
