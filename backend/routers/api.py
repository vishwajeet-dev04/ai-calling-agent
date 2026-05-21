import asyncio
import json
import logging
from fastapi import APIRouter, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse
from services.excel_service import parse_excel, export_excel
from services.queue_service import run_call_queue, stop_queue
from utils.store import store
from io import BytesIO

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["api"])


@router.post("/upload")
async def upload_excel(file: UploadFile = File(...)):
    if not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(400, "Only .xlsx or .xls files are accepted.")
    if store.queue_running:
        raise HTTPException(400, "Cannot upload while queue is running. Stop the queue first.")
    contents = await file.read()
    try:
        candidates = parse_excel(contents)
    except ValueError as e:
        raise HTTPException(400, str(e))
    store.load_candidates(candidates)
    logger.info(f"Uploaded {len(candidates)} candidates.")
    return {
        "message": f"Loaded {len(candidates)} candidates successfully.",
        "candidates": [c.model_dump() for c in candidates],
    }


@router.post("/start-queue")
async def start_queue(background_tasks: BackgroundTasks):
    if store.queue_running:
        raise HTTPException(400, "Queue is already running.")
    if not store.candidates:
        raise HTTPException(400, "No candidates loaded. Upload an Excel file first.")
    pending = [c for c in store.candidates if c.status.value == "pending"]
    if not pending:
        raise HTTPException(400, "No pending candidates.")
    background_tasks.add_task(run_call_queue)
    return {"message": f"Call queue started. {len(pending)} calls pending."}


@router.post("/stop-queue")
async def stop_queue_endpoint():
    stop_queue()
    return {"message": "Queue stop requested."}


@router.post("/reset")
async def reset():
    if store.queue_running:
        raise HTTPException(400, "Stop the queue before resetting.")
    for c in store.candidates:
        c.status = "pending"
        c.call_sid = None
        c.error_message = None
        c.overall_satisfaction = None
        c.would_recommend = None
        c.issues_faced = None
        c.suggestions = None
        c.call_duration = None
    store.call_sessions.clear()
    store.call_events.clear()
    return {"message": f"Reset {len(store.candidates)} candidates to pending."}


@router.get("/status")
async def get_status():
    return store.get_queue_stats()


@router.get("/candidates")
async def get_candidates():
    return [c.model_dump() for c in store.candidates]


@router.get("/status/stream")
async def status_stream():
    """Server-Sent Events for live updates."""
    async def generator():
        while True:
            payload = json.dumps({
                "stats": store.get_queue_stats(),
                "candidates": [c.model_dump() for c in store.candidates],
            })
            yield f"data: {payload}\n\n"
            await asyncio.sleep(2)
    return StreamingResponse(generator(), media_type="text/event-stream",
                              headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/download")
async def download_results():
    if not store.candidates:
        raise HTTPException(404, "No data to export.")
    excel_bytes = export_excel(store.candidates)
    return StreamingResponse(
        BytesIO(excel_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=survey_results.xlsx"},
    )