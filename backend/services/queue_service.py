"""
Queue Service
=============
Calls candidates one by one. Uses asyncio.Event to wait for each call
to truly finish (via the /webhook/call-status callback) instead of polling.
"""

import asyncio
import logging
from models.schemas import CallStatus
from services.twilio_service import make_call
from utils.store import store

logger = logging.getLogger(__name__)

DELAY_BETWEEN_CALLS = 8   # seconds between consecutive calls
CALL_TIMEOUT = 180        # max seconds to wait for a call to complete


async def run_call_queue():
    store.queue_running = True
    logger.info("═══ Call queue started ═══")

    while store.queue_running:
        candidate = store.get_next_pending()

        if not candidate:
            logger.info("✓ All candidates processed. Queue complete.")
            break

        logger.info(f"▶ Calling: {candidate.name} ({candidate.phone})")
        store.update_candidate_status(candidate.id, CallStatus.IN_PROGRESS)

        try:
            call_sid = make_call(candidate.phone, candidate.id)
            store.update_candidate_status(candidate.id, CallStatus.IN_PROGRESS, call_sid=call_sid)
            store.init_call_session(call_sid, candidate.name)
            logger.info(f"  SID: {call_sid}")

            # Wait for the call-status webhook to fire (event-based, not polling)
            event = store.get_call_event(call_sid)
            if event:
                try:
                    await asyncio.wait_for(event.wait(), timeout=CALL_TIMEOUT)
                    logger.info(f"  Call completed for {candidate.name}")
                except asyncio.TimeoutError:
                    logger.warning(f"  Timeout waiting for {candidate.name} — marking failed")
                    store.update_candidate_status(
                        candidate.id, CallStatus.FAILED,
                        error_message="Call timed out waiting for status callback"
                    )

        except Exception as e:
            logger.error(f"  Failed to call {candidate.name}: {e}")
            store.update_candidate_status(
                candidate.id, CallStatus.FAILED, error_message=str(e)
            )

        if store.queue_running:
            logger.info(f"  Waiting {DELAY_BETWEEN_CALLS}s before next call...")
            await asyncio.sleep(DELAY_BETWEEN_CALLS)

    store.queue_running = False
    logger.info("═══ Queue runner exited ═══")


def stop_queue():
    store.queue_running = False
    logger.info("Queue stop requested.")