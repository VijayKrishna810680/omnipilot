"""What OmniPilot remembers about you (you can add or remove facts)."""
import streamlit as st

from core.ui import get_agent

agent = get_agent()
st.title("Memory")
st.caption("OmniPilot uses these facts in every chat. Tell it things like 'I prefer PDF reports' and it will remember.")
new = st.text_input("Add a fact", placeholder="e.g. I work as a data engineer at a startup")
if st.button("Save", disabled=not new):
    agent.ctx.memory.add(new)
    st.rerun()
facts = agent.ctx.memory.all()
if not facts:
    st.info("Nothing remembered yet.")
for f in facts:
    c1, c2 = st.columns([8, 1])
    c1.markdown(f"- {f['text']}  \n<small>{f['created']}</small>", unsafe_allow_html=True)
    if c2.button("🗑️", key=f"m{f['id']}"):
        agent.ctx.memory.delete(f["id"])
        st.rerun()
