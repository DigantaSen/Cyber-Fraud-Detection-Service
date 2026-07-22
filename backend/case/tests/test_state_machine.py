"""Pure unit tests for the state machine — no async, no DB."""
import pytest
from state_machine.transitions import (
    validate_transition, TransitionError, TransitionPermissionError,
    get_allowed_transitions, VALID_STATES,
)


class TestValidTransitions:

    def test_new_to_assigned_investigator(self):
        validate_transition("New", "Assigned", caller_role="INVESTIGATOR")

    def test_assigned_to_investigating(self):
        validate_transition("Assigned", "Investigating", caller_role="INVESTIGATOR")

    def test_pending_ai_to_investigating_ai_timeout(self):
        validate_transition("Pending_AI", "Investigating", reason="AI_TIMEOUT", caller_role="SYSTEM")

    def test_pending_ai_to_action_taken(self):
        validate_transition("Pending_AI", "Action_Taken", caller_role="SYSTEM")

    def test_pending_ai_to_closed(self):
        validate_transition("Pending_AI", "Closed", caller_role="INVESTIGATOR")


class TestInvalidTransitions:

    def test_new_to_closed_invalid(self):
        with pytest.raises(TransitionError):
            validate_transition("New", "Closed", caller_role="INVESTIGATOR")

    def test_closed_is_terminal(self):
        with pytest.raises(TransitionError):
            validate_transition("Closed", "Assigned", caller_role="ADMIN")

    def test_unknown_target_state(self):
        with pytest.raises(TransitionError):
            validate_transition("New", "HACKED", caller_role="ADMIN")

    def test_wrong_reason_for_ai_timeout(self):
        with pytest.raises(TransitionError):
            validate_transition("Pending_AI", "Investigating", reason="WRONG", caller_role="SYSTEM")


class TestRoleRestrictions:

    def test_citizen_cannot_assign(self):
        with pytest.raises(TransitionPermissionError):
            validate_transition("New", "Assigned", caller_role="CITIZEN")

    def test_admin_can_assign(self):
        validate_transition("New", "Assigned", caller_role="ADMIN")


class TestHelpers:

    def test_get_allowed_transitions_new(self):
        allowed = get_allowed_transitions("New")
        assert "Assigned" in allowed
        assert "Closed" not in allowed

    def test_get_allowed_transitions_closed(self):
        allowed = get_allowed_transitions("Closed")
        assert allowed == []

    def test_all_states_defined(self):
        assert "New" in VALID_STATES
        assert "Pending_AI" in VALID_STATES
        assert "Closed" in VALID_STATES
