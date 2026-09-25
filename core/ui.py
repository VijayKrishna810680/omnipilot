"""Shared Streamlit helpers: per-user identity, secrets, and the session's agent."""
from __future__ import annotations

import os
import uuid

import streamlit as st

from core.activity import ActivityLog
from core.agent import Agent
from core.memory import Memory
from core.router import PROVIDERS, Router
from core.workspace import Workspace

KEY_NAMES = ["GROQ_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY", "OPENAI_API_KEY", "HF_TOKEN", "POLLINATIONS_TOKEN", "TAVILY_API_KEY"]


def load_secrets() -> None:
    """Copy keys from Streamlit secrets (cloud) into the environment."""
    try:
        for k in KEY_NAMES + ["OLLAMA_URL", "OLLAMA_MODEL"]:
            if k in st.secrets and not os.getenv(k):
                os.environ[k] = str(st.secrets[k])
    except Exception:  # noqa: BLE001 -- no secrets file locally
        pass


def user_id() -> str:
    """A private id kept in the page URL, so bookmarking the link keeps your memory and files."""
    uid = st.query_params.get("u")
    if not uid or not uid.isalnum() or len(uid) > 32:
        uid = uuid.uuid4().hex[:16]
        st.query_params["u"] = uid
    return uid


def session_keys() -> dict:
    return st.session_state.setdefault("user_keys", {})


def get_agent() -> Agent:
    load_secrets()
    uid = user_id()
    if "agent" not in st.session_state or st.session_state.get("agent_uid") != uid:
        st.session_state.agent = Agent(Router(keys=session_keys()), Workspace(uid), Memory(user=uid), log=ActivityLog())
        st.session_state.agent_uid = uid
        st.session_state.history = []
    agent = st.session_state.agent
    agent.router.keys = {k: v for k, v in session_keys().items() if v}   # keys typed this session
    return agent


def provider_status(agent: Agent) -> list[tuple[str, bool]]:
    return [(name, name in agent.router.available()) for name in PROVIDERS if name != "ollama" or os.getenv("OLLAMA_URL")]
