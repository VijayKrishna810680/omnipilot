"""All files OmniPilot created or you uploaded in this workspace."""
import mimetypes

import streamlit as st

from core.ui import get_agent

agent = get_agent()
st.title("My files")
st.caption("Everything OmniPilot made for you. Bookmark this page's link to come back to the same files and memory.")
files = agent.ctx.workspace.files()
if not files:
    st.info("No files yet. Ask OmniPilot to create a document, spreadsheet, image or project.")
for i, p in enumerate(files):
    rel = agent.ctx.workspace.rel(p)
    mime = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
    c1, c2, c3 = st.columns([5, 2, 2])
    c1.markdown(f"**{rel}**  \n{p.stat().st_size / 1024:.1f} KB")
    c2.download_button("Download", p.read_bytes(), file_name=p.name, mime=mime, key=f"d{i}")
    if c3.button("Remove", key=f"r{i}"):
        p.unlink()
        st.rerun()
    if mime.startswith("image/"):
        st.image(str(p), width=320)
