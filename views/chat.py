"""Main chat: talk to OmniPilot, watch it work, approve risky steps, download what it makes."""
import json
import re
import mimetypes

import streamlit as st

from core.ui import get_agent, provider_status, session_keys

TOOL_LABELS = {
    "create_document": "📄 Writing document", "create_presentation": "📽️ Building slides",
    "create_excel": "📊 Building spreadsheet", "analyze_file": "🔎 Analyzing file",
    "generate_image": "🎨 Generating image", "write_file": "💾 Writing file", "read_file": "📖 Reading file",
    "list_files": "🗂️ Listing files", "run_python": "🐍 Running code", "zip_project": "📦 Zipping project",
    "remember": "🧠 Saving to memory", "recall": "🧠 Searching memory",
}

agent = get_agent()
history = st.session_state.setdefault("history", [])

# ------------------------------------------------------------------ sidebar
with st.sidebar:
    if st.button("➕ New chat", use_container_width=True):
        agent.messages, agent.pending = [], None
        st.session_state.history = []
        st.rerun()
    st.subheader("AI models")
    status = provider_status(agent)
    for name, ok in status:
        st.caption(f"{'🟢' if ok else '⚪'} {name}")
    if not any(ok for _, ok in status):
        st.warning("Add a free key to start chatting.")
    with st.expander("Add your own API key"):
        st.caption("Used only in this browser session. Never stored or logged.")
        for k in ["GROQ_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY"]:
            v = st.text_input(k, type="password", key=f"in_{k}")
            if v:
                session_keys()[k] = v
    agent.auto_approve = not st.toggle("Ask before running code", value=True,
                                       help="OmniPilot pauses and shows you the code before running it")
    up = st.file_uploader("Upload a file (CSV, Excel, text...)", accept_multiple_files=False)
    if up is not None and st.session_state.get("last_upload") != (up.name, up.size):
        agent.ctx.workspace.path(up.name).write_bytes(up.getvalue())
        st.session_state.last_upload = (up.name, up.size)
        st.success(f"Uploaded {up.name}. Ask me about it!")


# ------------------------------------------------------------------ rendering helpers
def show_file(rel: str, key: str):
    p = agent.ctx.workspace.path(rel)
    if not p.exists():
        return
    mime = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
    if mime.startswith("image/"):
        st.image(str(p), caption=rel)
    st.download_button(f"⬇️ {rel}", p.read_bytes(), file_name=p.name, mime=mime, key=key)


def show_step(ev: dict, key: str):
    d = ev["data"]
    if ev["type"] == "tool_result":
        label = TOOL_LABELS.get(d["tool"], d["tool"])
        with st.expander(f"{'✅' if d['ok'] else '⚠️'} {label}", expanded=False):
            st.code(str(d.get("output", ""))[:3000])
    elif ev["type"] == "approval":
        args = json.loads(d["arguments"]) if d["arguments"].startswith("{") else {}
        st.info("OmniPilot wants to run this code:")
        st.code(args.get("code", d["arguments"]), language="python")


def clean(text: str) -> str:
    """Models sometimes put HTML line breaks in Markdown tables; show them as separators."""
    return re.sub(r"<br\s*/?>", "; ", text)


def show_error(message: str):
    if "rate limit" in message.lower() or "429" in message:
        st.warning("The free AI models are busy (free-tier limit reached). Wait about a minute, "
                   "then type **continue** and I'll pick up where I stopped.")
        with st.expander("Details"):
            st.code(message[:1500])
    else:
        st.error(message)


def show_assistant(turn: dict, idx: int):
    for j, ev in enumerate(turn["steps"]):
        show_step(ev, f"s{idx}_{j}")
    files = [f for ev in turn["steps"] if ev["type"] == "tool_result" for f in ev["data"].get("files") or []]
    for j, f in enumerate(dict.fromkeys(files)):
        show_file(f, f"f{idx}_{j}_{f}")
    if turn.get("text"):
        st.markdown(clean(turn["text"]))
    if turn.get("error"):
        show_error(turn["error"])
    if turn.get("model"):
        st.caption(f"via {turn['model']}")


def run_events(events, turn: dict):
    """Consume agent events, update the UI live and record them in the turn."""
    box = st.status("Working...", expanded=True)
    for ev in events:
        rec = {"type": ev.type, "data": ev.data}
        if ev.type == "model":
            turn["model"] = f"{ev.data['provider']} / {ev.data['model']}"
            if ev.data["has_tools"]:
                box.update(label="Thinking and using tools...")
        elif ev.type == "tool_start":
            box.write(TOOL_LABELS.get(ev.data["tool"], ev.data["tool"]) + "...")
        elif ev.type == "tool_result":
            turn["steps"].append(rec)
            box.write(("✅ " if ev.data["ok"] else "⚠️ ") + TOOL_LABELS.get(ev.data["tool"], ev.data["tool"]))
        elif ev.type == "approval":
            turn["steps"].append(rec)
            turn["waiting"] = True
        elif ev.type == "final":
            turn["text"] = ev.data["text"]
            turn["waiting"] = False
        elif ev.type == "error":
            turn["error"] = ev.data["message"]
    box.update(label="Waiting for your approval" if turn.get("waiting") else "Done", state="complete",
               expanded=False)


# ------------------------------------------------------------------ page
st.title("OmniPilot")
if not history:
    st.caption("Chat, create documents, spreadsheets, slides and images, build and test code projects, "
               "and analyze your files — all in one place.")
    examples = ["Write a one-page business plan for a coffee shop as a Word document",
                "Make an Excel budget for a family with monthly totals and a pie chart",
                "Generate an image of a futuristic Indian city at sunset, cinematic",
                "Build a small Python to-do app with tests, run the tests, and give me a zip",
                "Create a 5-slide presentation about the future of AI agents",
                "Explain the difference between RAG and fine-tuning simply"]
    cols = st.columns(2)
    for i, ex in enumerate(examples):
        if cols[i % 2].button(ex, use_container_width=True, key=f"ex{i}"):
            st.session_state.queued = ex
            st.rerun()

for i, turn in enumerate(history):
    with st.chat_message(turn["role"]):
        if turn["role"] == "user":
            st.markdown(turn["text"])
        else:
            show_assistant(turn, i)

# approval buttons for a paused action
if agent.pending and history and history[-1].get("waiting"):
    c1, c2, _ = st.columns([1, 1, 4])
    if c1.button("✅ Approve", type="primary"):
        turn = history[-1]
        with st.chat_message("assistant"):
            run_events(agent.resume(True), turn)
        st.rerun()
    if c2.button("❌ Deny"):
        turn = history[-1]
        with st.chat_message("assistant"):
            run_events(agent.resume(False), turn)
        st.rerun()

prompt = st.chat_input("Message OmniPilot...", disabled=bool(agent.pending)) or st.session_state.pop("queued", None)
if prompt:
    history.append({"role": "user", "text": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    turn = {"role": "assistant", "steps": [], "text": "", "waiting": False}
    history.append(turn)
    with st.chat_message("assistant"):
        run_events(agent.send(prompt), turn)
    st.rerun()
