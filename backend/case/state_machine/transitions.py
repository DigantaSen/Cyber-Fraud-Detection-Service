"""
Case State Machine — Execution.md T5a spec.

Valid states: New, Assigned, Investigating, Pending_AI, Action_Taken, Closed
State graph: all valid (from_state, to_state) pairs.
Special rule: Pending_AI → Investigating only when reason in ("AI_TIMEOUT", "HITL_APPROVED")

Usage:
    from state_machine.transitions import validate_transition, TransitionError

    validate_transition(
        current_state="Pending_AI",
        new_state="Investigating",
        reason="AI_TIMEOUT",
        caller_role="SYSTEM",
    )
"""

# ── State graph ────────────────────────────────────────────────────────────────
# frozenset gives O(1) membership test and is immutable at module level.

VALID_TRANSITIONS: frozenset[tuple[str, str]] = frozenset({
    ("New",           "Assigned"),
    ("New",           "Pending_AI"),  # inference could not produce an automatable verdict
    ("Assigned",      "Investigating"),
    ("Investigating", "Pending_AI"),
    ("Pending_AI",    "Investigating"),   # AI_TIMEOUT re-entry OR HITL review restart
    ("Pending_AI",    "Action_Taken"),   # HITL APPROVE → resume automated actions
    ("Pending_AI",    "Closed"),          # HITL REJECT → disposition = FALSE_POSITIVE
    ("Action_Taken",  "Closed"),
})

# Transitions that require the caller to supply a specific reason value.
REASON_REQUIRED_TRANSITIONS: dict[tuple[str, str], list[str]] = {
    ("Pending_AI", "Investigating"): ["AI_TIMEOUT", "HITL_APPROVED"],
}

# Roles permitted to trigger each transition.
# "SYSTEM" = internal service-to-service call (Orchestrator, no user JWT).
ROLE_ALLOWED_TRANSITIONS: dict[tuple[str, str], list[str]] = {
    ("New",           "Assigned"):       ["INVESTIGATOR", "ADMIN"],
    ("New",           "Pending_AI"):     ["SYSTEM"],
    ("Assigned",      "Investigating"):  ["INVESTIGATOR", "ADMIN"],
    ("Investigating",  "Pending_AI"):    ["SYSTEM"],
    ("Pending_AI",    "Investigating"):  ["SYSTEM", "INVESTIGATOR", "ADMIN"],
    ("Pending_AI",    "Action_Taken"):   ["SYSTEM", "INVESTIGATOR", "ADMIN"],
    ("Pending_AI",    "Closed"):         ["INVESTIGATOR", "ADMIN"],
    ("Action_Taken",  "Closed"):         ["INVESTIGATOR", "ADMIN"],
}

# Terminal states — no outgoing transitions allowed.
TERMINAL_STATES: frozenset[str] = frozenset({"Closed"})

# All valid state names (must match DB CHECK constraint exactly).
VALID_STATES: frozenset[str] = frozenset({
    "New", "Assigned", "Investigating", "Pending_AI", "Action_Taken", "Closed"
})


# ── Domain exceptions (router converts to HTTP 422) ───────────────────────────

class TransitionError(Exception):
    """Raised when a requested state transition is not permitted."""

    def __init__(self, current: str, target: str, reason: str = ""):
        self.current = current
        self.target = target
        self.detail = reason
        msg = f"Invalid transition: {current} → {target}"
        if reason:
            msg += f" ({reason})"
        super().__init__(msg)


class TransitionPermissionError(Exception):
    """Raised when the caller's role is not authorised for this transition."""

    def __init__(self, role: str, current: str, target: str):
        self.role = role
        self.current = current
        self.target = target
        super().__init__(
            f"Role '{role}' is not authorised to transition case from {current} to {target}"
        )


# ── Public API ─────────────────────────────────────────────────────────────────

def validate_transition(
    current_state: str,
    new_state: str,
    reason: str = "",
    caller_role: str = "SYSTEM",
) -> None:
    """
    Validate a case state transition.
    Pure function — no I/O.  Call BEFORE any DB write.

    Raises:
        TransitionError:           if the (from, to) pair or reason is invalid.
        TransitionPermissionError: if caller_role is not authorised.

    Args:
        current_state: current ``Case.status`` value read from the DB.
        new_state:     requested target state from the request body.
        reason:        free-text reason supplied by the caller (required for some transitions).
        caller_role:   JWT ``role`` claim, or ``"SYSTEM"`` for internal service calls.
    """
    # 1. Target must be a known state.
    if new_state not in VALID_STATES:
        raise TransitionError(
            current_state, new_state, f"'{new_state}' is not a recognised case state"
        )

    # 2. Terminal states have no outgoing edges.
    if current_state in TERMINAL_STATES:
        raise TransitionError(
            current_state, new_state, "case is in a terminal state and cannot be transitioned"
        )

    pair = (current_state, new_state)

    # 3. The (from, to) edge must exist in the graph.
    if pair not in VALID_TRANSITIONS:
        raise TransitionError(current_state, new_state)

    # 4. Caller role must be on the allow-list for this edge.
    allowed_roles = ROLE_ALLOWED_TRANSITIONS.get(pair, [])
    if caller_role not in allowed_roles:
        raise TransitionPermissionError(caller_role, current_state, new_state)

    # 5. Some transitions require a specific reason value.
    required_reasons = REASON_REQUIRED_TRANSITIONS.get(pair)
    if required_reasons and reason not in required_reasons:
        raise TransitionError(
            current_state,
            new_state,
            f"reason must be one of {required_reasons}, got '{reason}'",
        )


def get_allowed_transitions(current_state: str) -> list[str]:
    """Return all target states reachable from ``current_state``."""
    return [to for (frm, to) in VALID_TRANSITIONS if frm == current_state]
