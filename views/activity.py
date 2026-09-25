"""Monitoring: every model call and tool call, with success and timing."""
import pandas as pd
import streamlit as st

from core.ui import get_agent

agent = get_agent()
st.title("Activity")
log = pd.DataFrame(agent.log.recent())
if log.empty:
    st.info("No activity yet.")
    st.stop()
mine = log[log["session"] == agent.ctx.workspace.session_id]
c1, c2, c3 = st.columns(3)
c1.metric("Model calls", int((mine["kind"] == "model").sum()))
c2.metric("Tool calls", int((mine["kind"] == "tool").sum()))
c3.metric("Tool success rate", f"{100 * mine[mine['kind'] == 'tool']['ok'].mean():.0f}%" if (mine["kind"] == "tool").any() else "-")
st.dataframe(mine[["ts", "kind", "name", "ok", "seconds", "detail"]], use_container_width=True, hide_index=True)
