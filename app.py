"""
OmniPilot - an all-in-one AI agent: chat, documents, spreadsheets, slides, images, code projects, memory.
Run:  streamlit run app.py
"""
import streamlit as st

st.set_page_config(page_title="OmniPilot", page_icon="🧭", layout="wide")

st.navigation([
    st.Page("views/chat.py", title="Chat", icon="💬", default=True),
    st.Page("views/files.py", title="My files", icon="🗂️"),
    st.Page("views/memory.py", title="Memory", icon="🧠"),
    st.Page("views/activity.py", title="Activity", icon="📈"),
]).run()
