import asyncio
import logging
from models.schemas import CallStatus
from services.twilio_service import make_call
from utils.store import store

logger = logging.getLogger(__name__)

DELAY_BETWEEN_CALLS = 8
CALL_TIMEOUT = 300  # 5 minutes max per call


async def run_call_queue():
    store.queue_running = True
    logger.info("═══ Call queue started ═══")

    while store.queue_running:
        candidate = store.get_next_pending()
        if not candidate:
            logger.info("✓ All candidates processed.")
            break

        logger.info(f"▶ Calling: {candidate.name} ({candidate.phone})")
        store.update_candidate_status(candidate.id, CallStatus.IN_PROGRESS)

        try:
            call_sid = make_call(candidate.phone, candidate.id)
            # Update candidate with SID BEFORE initializing session
            store.update_candidate_status(candidate.id, CallStatus.IN_PROGRESS, call_sid=call_sid)
            # Init session AFTER call_sid is linked
            store.init_call_session(call_sid, candidate.name)
            logger.info(f"  SID: {call_sid}")

            # Wait for FINAL call-status (completed/failed/no-answer)
            # The event is set only by final statuses, not initiated/ringing/in-progress
            event = store.get_call_event(call_sid)
            if event:
                try:
                    await asyncio.wait_for(event.wait(), timeout=CALL_TIMEOUT)
                    logger.info(f"  ✓ Call done: {candidate.name}")
                except asyncio.TimeoutError:
                    logger.warning(f"  Timeout for {candidate.name}")
                    store.update_candidate_status(candidate.id, CallStatus.FAILED,
                                                   error_message="Timed out")

        except Exception as e:
            logger.error(f"  Error calling {candidate.name}: {e}")
            store.update_candidate_status(candidate.id, CallStatus.FAILED, error_message=str(e))

        if store.queue_running:
            logger.info(f"  Waiting {DELAY_BETWEEN_CALLS}s...")
            await asyncio.sleep(DELAY_BETWEEN_CALLS)

    store.queue_running = False
    logger.info("═══ Queue exited ═══")


def stop_queue():
    store.queue_running = False
    logger.info("Queue stopped.")