import streamlit as st
import requests
import pandas as pd
import time
from io import BytesIO

API_BASE = "http://localhost:8000"

st.set_page_config(page_title="AI Calling Agent", page_icon="📞", layout="wide")

st.markdown("""
<style>
    .badge { display:inline-block; padding:3px 10px; border-radius:12px; font-size:12px; font-weight:600; }
    .badge-pending     { background:#FFF3CD; color:#856404; }
    .badge-in_progress { background:#CCE5FF; color:#004085; }
    .badge-completed   { background:#D4EDDA; color:#155724; }
    .badge-failed      { background:#F8D7DA; color:#721C24; }
    .badge-no_answer   { background:#E2E3E5; color:#383D41; }
    .live-dot { display:inline-block; width:8px; height:8px; border-radius:50%;
                background:#28a745; margin-right:5px; animation:pulse 1.2s infinite; }
    @keyframes pulse { 0%{opacity:1} 50%{opacity:0.3} 100%{opacity:1} }
    [data-testid="metric-container"] {
        background:#f8f9fa; border:1px solid #e9ecef; border-radius:10px; padding:12px;
    }
    table { width:100%; border-collapse:collapse; font-size:13px; }
    th { background:#f1f3f5; padding:8px 10px; text-align:left; font-weight:600; }
    td { padding:7px 10px; border-bottom:1px solid #f1f3f5; vertical-align:top; }
</style>
""", unsafe_allow_html=True)


def badge(status):
    labels = {
        "pending":     ("⏳", "Pending",     "badge-pending"),
        "in_progress": ("📞", "In Progress", "badge-in_progress"),
        "completed":   ("✅", "Completed",   "badge-completed"),
        "failed":      ("❌", "Failed",      "badge-failed"),
        "no_answer":   ("📵", "No Answer",   "badge-no_answer"),
    }
    icon, label, cls = labels.get(status, ("?", status, "badge-pending"))
    return f'<span class="badge {cls}">{icon} {label}</span>'


def fetch_status():
    try:
        r = requests.get(f"{API_BASE}/api/status", timeout=3)
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None


def fetch_candidates():
    try:
        r = requests.get(f"{API_BASE}/api/candidates", timeout=3)
        return r.json() if r.status_code == 200 else []
    except Exception:
        return []


# ── Header ────────────────────────────────────────────────────────────────────
st.title("📞 AI Calling Agent")
st.caption("Upload candidates → Start queue → Monitor live → Download results")
st.divider()

# ── Section 1: Upload ─────────────────────────────────────────────────────────
st.subheader("① Upload Candidates")

col_up, col_tpl = st.columns([3, 1])

with col_tpl:
    st.markdown("**Need a template?**")
    tpl = pd.DataFrame({"name": ["John Doe", "Jane Smith"],
                         "phone": ["+919876543210", "+919123456789"]})
    buf = BytesIO()
    tpl.to_excel(buf, index=False)
    buf.seek(0)
    st.download_button("⬇ Download template", data=buf,
                        file_name="template.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

with col_up:
    uploaded_file = st.file_uploader(
        "Drop your Excel file (.xlsx) — Required columns: **name**, **phone**",
        type=["xlsx", "xls"],
    )
    # ── CRITICAL: only upload when button is clicked, NOT on every rerun ──
    if uploaded_file:
        if st.button("📤 Upload & Load Candidates", type="primary"):
            with st.spinner("Uploading..."):
                resp = requests.post(
                    f"{API_BASE}/api/upload",
                    files={"file": (uploaded_file.name, uploaded_file.getvalue())},
                )
            if resp.status_code == 200:
                data = resp.json()
                st.success(data["message"])
                df = pd.DataFrame(data["candidates"])[["name", "phone", "status"]]
                st.dataframe(df, use_container_width=True, hide_index=True)
            else:
                try:
                    detail = resp.json().get("detail", "Unknown error")
                except Exception:
                    detail = resp.text
                st.error(f"Upload failed: {detail}")

st.divider()

# ── Section 2: Queue Control ──────────────────────────────────────────────────
st.subheader("② Queue Control")

c1, c2, c3, _ = st.columns([1, 1, 1, 3])

with c1:
    if st.button("▶ Start Calling", type="primary", use_container_width=True):
        r = requests.post(f"{API_BASE}/api/start-queue")
        if r.status_code == 200:
            st.success(r.json()["message"])
        else:
            st.error(r.json().get("detail", "Error"))

with c2:
    if st.button("⏹ Stop Queue", use_container_width=True):
        r = requests.post(f"{API_BASE}/api/stop-queue")
        st.info(r.json().get("message", "Stopped"))

with c3:
    if st.button("🔄 Reset All", use_container_width=True):
        r = requests.post(f"{API_BASE}/api/reset")
        if r.status_code == 200:
            st.success(r.json()["message"])
        else:
            st.error(r.json().get("detail", "Error"))

st.divider()

# ── Section 3: Live Monitor ───────────────────────────────────────────────────
st.subheader("③ Live Monitor")

auto_refresh = st.toggle("🔴 Auto-refresh (every 3s)", value=True)

status_block = st.empty()
table_block  = st.empty()


def render():
    stats = fetch_status()
    candidates = fetch_candidates()

    with status_block.container():
        if not stats:
            st.error("⚠️ Cannot connect to backend on port 8000.")
            return

        running = stats.get("queue_running", False)
        current = stats.get("current_candidate")

        cols = st.columns(6)
        cols[0].metric("Total",       stats.get("total", 0))
        cols[1].metric("Pending",     stats.get("pending", 0))
        cols[2].metric("In Progress", stats.get("in_progress", 0))
        cols[3].metric("Completed",   stats.get("completed", 0))
        cols[4].metric("Failed",      stats.get("failed", 0))
        cols[5].metric("No Answer",   stats.get("no_answer", 0))

        if running:
            st.markdown(
                f'<span class="live-dot"></span> Queue running — calling: <strong>{current or "Starting..."}</strong>',
                unsafe_allow_html=True,
            )
        else:
            total = stats.get("total", 0)
            done = stats.get("completed", 0) + stats.get("failed", 0) + stats.get("no_answer", 0)
            if total > 0 and done == total:
                st.success("✅ All calls completed!")
            else:
                st.warning("⏸ Queue is not running")

    if candidates:
        cols_show = ["name", "phone", "status", "overall_satisfaction",
                     "would_recommend", "issues_faced", "suggestions", "call_duration"]
        df = pd.DataFrame(candidates)
        avail = [c for c in cols_show if c in df.columns]
        df_show = df[avail].copy()
        df_show["status"] = df_show["status"].apply(badge)
        df_show.columns = [c.replace("_", " ").title() for c in df_show.columns]

        with table_block.container():
            st.write(df_show.to_html(escape=False, index=False), unsafe_allow_html=True)


render()

if auto_refresh:
    time.sleep(3)
    st.rerun()

st.divider()

# ── Section 4: Download ───────────────────────────────────────────────────────
st.subheader("④ Download Results")

if st.button("⬇ Export Survey Results"):
    r = requests.get(f"{API_BASE}/api/download")
    if r.status_code == 200:
        st.download_button(
            label="📥 Save survey_results.xlsx",
            data=r.content,
            file_name="survey_results.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    else:
        st.error("No data available yet.")

st.divider()
st.caption("AI Calling Agent v2 · Twilio STT/TTS · Groq LLaMA-3.3 · Node-based graph")