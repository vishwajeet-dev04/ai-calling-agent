"""
Webhook Router
"""

import logging
from fastapi import APIRouter, Request, Form, Query
from fastapi.responses import Response
from graph.nodes import greeting_node, route, DEFAULT_SURVEY_QUESTIONS
from services.twilio_service import (
    build_greeting_twiml,
    build_agent_twiml,
    build_no_input_twiml,
    build_error_twiml,
)
from models.schemas import CallStatus as CandidateCallStatus
from utils.store import store

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhook", tags=["webhook"])
XML = "application/xml"


@router.post("/call-start")
async def call_start(candidate_id: int = Query(...)):
    try:
        candidate = next((c for c in store.candidates if c.id == candidate_id), None)
        if not candidate:
            logger.error(f"call-start: candidate {candidate_id} not found")
            return Response(content=build_error_twiml(), media_type=XML)

        greeting_text = greeting_node(candidate.name)
        logger.info(f"Greeting for {candidate.name}: {greeting_text[:80]}...")
        return Response(content=build_greeting_twiml(greeting_text, candidate_id), media_type=XML)

    except Exception as e:
        logger.error(f"call-start error: {e}", exc_info=True)
        return Response(content=build_error_twiml(), media_type=XML)


@router.post("/gather")
async def gather(
    candidate_id: int = Query(...),
    SpeechResult: str = Form(default=""),
    CallSid: str = Form(default=""),
    Confidence: str = Form(default="0"),
):
    try:
        speech = SpeechResult.strip()
        confidence = float(Confidence) if Confidence else 0.0
        logger.info(f"Gather | SID:{CallSid} | confidence:{confidence:.2f} | input:'{speech[:60]}'")

        # Low confidence — treat as empty
        if speech and confidence < 0.3:
            logger.info("Low confidence — treating as no input")
            speech = ""

        # Get session — NEVER reinitialize if it already exists
        session = store.get_session(CallSid)
        if not session:
            # Session missing — can happen if server restarted mid-call
            candidate = next((c for c in store.candidates if c.id == candidate_id), None)
            name = candidate.name if candidate else "there"
            store.init_call_session(CallSid, name)
            # Also re-link call_sid to candidate
            if candidate:
                store.update_candidate_status(candidate.id, CandidateCallStatus.IN_PROGRESS, call_sid=CallSid)
            session = store.get_session(CallSid)

        # Route through graph nodes
        agent_text, updated_session = route(session, speech)
        store.call_sessions[CallSid] = updated_session

        phase = updated_session.get("phase")
        is_final = phase in ("closing", "ended")

        logger.info(f"Agent [{phase}]: {agent_text[:80]}...")

        # Save answers to candidate record on EVERY turn (not just at end)
        answers = updated_session.get("answers", {})
        if answers:
            store.update_by_call_sid(CallSid, **answers)

        # If call is ending, update status to completed
        if is_final:
            candidate = next((c for c in store.candidates if c.id == candidate_id), None)
            if candidate:
                store.update_candidate_status(
                    candidate.id,
                    CandidateCallStatus.COMPLETED,
                    **answers
                )

        return Response(content=build_agent_twiml(agent_text, candidate_id, is_final=is_final), media_type=XML)

    except Exception as e:
        logger.error(f"gather error: {e}", exc_info=True)
        return Response(content=build_error_twiml(), media_type=XML)


@router.post("/no-input")
async def no_input(
    candidate_id: int = Query(...),
    attempt: int = Query(default=1),
    CallSid: str = Form(default=""),
):
    logger.info(f"No input | SID:{CallSid} | attempt:{attempt}")
    return Response(content=build_no_input_twiml(candidate_id, attempt), media_type=XML)


@router.post("/call-status")
async def call_status(
    CallSid: str = Form(...),
    CallStatus: str = Form(...),
    CallDuration: str = Form(default="0"),
    AnsweredBy: str = Form(default=""),
):
    duration = int(CallDuration) if CallDuration.isdigit() else 0
    logger.info(f"Call status | SID:{CallSid} | status:{CallStatus} | duration:{duration}s | answeredBy:{AnsweredBy}")

    # Answering machine
    if AnsweredBy in ("machine_start", "machine_end_beep", "machine_end_silence", "fax"):
        logger.info(f"Answering machine for SID:{CallSid}")
        store.update_by_call_sid(CallSid, status=CandidateCallStatus.NO_ANSWER,
                                  error_message="Answering machine", call_duration=duration)
        store.signal_call_done(CallSid)
        store.clear_session(CallSid)
        return {"ok": True}

    status_map = {
        "completed":  CandidateCallStatus.COMPLETED,
        "failed":     CandidateCallStatus.FAILED,
        "busy":       CandidateCallStatus.FAILED,
        "no-answer":  CandidateCallStatus.NO_ANSWER,
        "canceled":   CandidateCallStatus.FAILED,
    }
    final_status = status_map.get(CallStatus.lower(), CandidateCallStatus.FAILED)

    # Pull final answers from session before clearing
    session = store.get_session(CallSid)
    answers = session.get("answers", {}) if session else {}

    store.update_by_call_sid(CallSid, status=final_status, call_duration=duration, **answers)

    store.signal_call_done(CallSid)
    store.clear_session(CallSid)
    return {"ok": True}