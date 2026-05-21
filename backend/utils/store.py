import asyncio
import logging
from typing import Dict, List, Optional
from models.schemas import Candidate, CallStatus
from collections import Counter

logger = logging.getLogger(__name__)


class Store:
    def __init__(self):
        self.candidates: List[Candidate] = []
        self.call_sessions: Dict[str, dict] = {}
        self.call_events: Dict[str, asyncio.Event] = {}
        self.queue_running: bool = False

    def load_candidates(self, candidates: List[Candidate]):
        if self.queue_running:
            logger.warning("Upload blocked: queue is running.")
            raise RuntimeError("Cannot upload while queue is running.")
        self.candidates = candidates
        self.call_sessions.clear()
        self.call_events.clear()
        logger.info(f"Loaded {len(candidates)} candidates.")

    def get_next_pending(self) -> Optional[Candidate]:
        return next((c for c in self.candidates if c.status == CallStatus.PENDING), None)

    def update_candidate_status(self, candidate_id: int, status: CallStatus, **kwargs):
        for c in self.candidates:
            if c.id == candidate_id:
                c.status = status
                for k, v in kwargs.items():
                    if hasattr(c, k):
                        setattr(c, k, v)
                logger.info(f"  {c.name} → {status.value}")
                break

    def update_by_call_sid(self, call_sid: str, **kwargs):
        for c in self.candidates:
            if c.call_sid == call_sid:
                for k, v in kwargs.items():
                    if not hasattr(c, k):
                        continue
                    if k == "status" and isinstance(v, str):
                        try:
                            v = CallStatus(v)
                        except ValueError:
                            continue
                    setattr(c, k, v)
                saved = [k for k in kwargs if k not in ("status", "call_duration", "error_message")]
                if saved:
                    logger.info(f"  Answers saved for {c.name}: {saved}")
                break

    def get_by_call_sid(self, call_sid: str) -> Optional[Candidate]:
        return next((c for c in self.candidates if c.call_sid == call_sid), None)

    def init_call_session(self, call_sid: str, candidate_name: str, questions: list = None):
        if call_sid in self.call_sessions:
            logger.debug(f"Session {call_sid[:16]}... already exists — skipping.")
            return
        from graph.nodes import DEFAULT_SURVEY_QUESTIONS
        self.call_sessions[call_sid] = {
            "candidate_name": candidate_name,
            "phase": "greeting",
            "question_index": 0,
            "answers": {},
            "conversation_history": [],
            "questions": questions or DEFAULT_SURVEY_QUESTIONS,
            "silence_retry": 0,
            "identity_retry": 0,
        }
        # Create event only if not already present
        if call_sid not in self.call_events:
            self.call_events[call_sid] = asyncio.Event()
        logger.info(f"Session ready for {candidate_name}")

    def get_session(self, call_sid: str) -> Optional[dict]:
        return self.call_sessions.get(call_sid)

    def clear_session(self, call_sid: str):
        self.call_sessions.pop(call_sid, None)
        event = self.call_events.pop(call_sid, None)
        if event:
            event.set()

    def get_call_event(self, call_sid: str) -> Optional[asyncio.Event]:
        return self.call_events.get(call_sid)

    def signal_call_done(self, call_sid: str):
        event = self.call_events.get(call_sid)
        if event:
            event.set()

    def get_queue_stats(self) -> dict:
        counts = Counter(c.status for c in self.candidates)
        current = next(
            (c.name for c in self.candidates if c.status == CallStatus.IN_PROGRESS), None
        )
        return {
            "total": len(self.candidates),
            "pending": counts.get(CallStatus.PENDING, 0),
            "in_progress": counts.get(CallStatus.IN_PROGRESS, 0),
            "completed": counts.get(CallStatus.COMPLETED, 0),
            "failed": counts.get(CallStatus.FAILED, 0),
            "no_answer": counts.get(CallStatus.NO_ANSWER, 0),
            "queue_running": self.queue_running,
            "current_candidate": current,
        }


store = Store()