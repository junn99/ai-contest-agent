from datetime import datetime
from src.models.enums import ContestState
import structlog

logger = structlog.get_logger(__name__)


class InvalidTransitionError(Exception):
    pass


# Valid transitions: {from_state: set(to_states)}
VALID_TRANSITIONS: dict[ContestState, set[ContestState]] = {
    ContestState.DISCOVERED: {ContestState.FILTERING},
    ContestState.FILTERING: {ContestState.SKIPPED, ContestState.ANALYZING},
    ContestState.ANALYZING: {
        ContestState.GENERATING,
        ContestState.SKIPPED,
        ContestState.FAILED,
        ContestState.RETRY,
    },
    ContestState.GENERATING: {
        ContestState.REVIEW_READY,
        ContestState.NEEDS_REVIEW,
        ContestState.FAILED,
        ContestState.RETRY,
    },
    ContestState.RETRY: {ContestState.ANALYZING, ContestState.GENERATING},
    ContestState.NEEDS_REVIEW: {ContestState.GENERATING, ContestState.SKIPPED},
    ContestState.REVIEW_READY: {
        ContestState.SUBMITTED,
        ContestState.GENERATING,
        ContestState.EXPIRED,
    },
    ContestState.SUBMITTED: {ContestState.TRACKING},
    ContestState.TRACKING: {ContestState.COMPLETED},
    ContestState.FAILED: {ContestState.RETRY},
    # Terminal states — no outgoing transitions
    ContestState.EXPIRED: set(),
    ContestState.SKIPPED: set(),
    ContestState.COMPLETED: set(),
}

TERMINAL_STATES = {ContestState.EXPIRED, ContestState.SKIPPED, ContestState.COMPLETED}
MAX_RETRIES = 3


class StateMachine:
    def __init__(self) -> None:
        self._transition_log: list[dict] = []

    def transition(
        self,
        current: ContestState,
        event: str,
        target: ContestState,
        retry_count: int = 0,
        contest_id: str = "",
    ) -> ContestState:
        allowed = VALID_TRANSITIONS.get(current, set())
        if target not in allowed:
            raise InvalidTransitionError(
                f"Invalid transition: {current!r} -> {target!r} (event={event!r})"
            )

        # Enforce retry cap
        if target == ContestState.RETRY and retry_count >= MAX_RETRIES:
            raise InvalidTransitionError(
                f"Max retries ({MAX_RETRIES}) reached for contest {contest_id!r}"
            )

        timestamp = datetime.utcnow().isoformat()
        entry = {
            "contest_id": contest_id,
            "from_state": current.value,
            "to_state": target.value,
            "event": event,
            "timestamp": timestamp,
        }
        self._transition_log.append(entry)

        logger.info(
            "state_transition",
            contest_id=contest_id,
            from_state=current.value,
            to_state=target.value,
            event_name=event,
            timestamp=timestamp,
        )

        return target

    def get_log(self) -> list[dict]:
        return list(self._transition_log)

    @staticmethod
    def is_terminal(state: ContestState) -> bool:
        return state in TERMINAL_STATES

    @staticmethod
    def allowed_targets(state: ContestState) -> set[ContestState]:
        return set(VALID_TRANSITIONS.get(state, set()))
