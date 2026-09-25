# OmniPilot

**An open-source, all-in-one AI agent.** Chat with it, and it can also **do the work**: write Word and PDF
documents, build Excel files with formulas and charts, make PowerPoint decks, generate images, build and
test code projects in a safe sandbox, analyze your files, and remember your preferences. It runs on
**free AI models**, with automatic switching between providers.

![tests](https://github.com/VijayKrishna810680/omnipilot/actions/workflows/ci.yml/badge.svg)

## What it can do

| Ask for... | OmniPilot... |
|---|---|
| "Write a business plan as a Word document" | writes the content and creates a `.docx` (or PDF) |
| "Make an Excel budget with totals and a pie chart" | builds an `.xlsx` with real formulas and an Excel chart |
| "Create a 5-slide deck about AI agents" | creates a `.pptx` with speaker notes |
| "Generate an image of a futuristic city" | generates the image and shows it in the chat |
| "Build a to-do app with tests and zip it" | writes the files, **runs the tests**, fixes errors, zips the project |
| "Analyze this CSV" (upload) | reads it, runs pandas code and draws charts |
| "I prefer PDF reports" | remembers it for future chats |

## How it works

```
You ──► Chat UI (Streamlit)
          │
          ▼
       Agent loop ── think ──► Model router ──► Groq → Gemini → OpenRouter → OpenAI → Ollama
          │                    (automatic fallback when a free limit is hit)
          │ tool calls
          ▼
   ┌──────────────┬───────────────┬──────────────┬──────────────┬─────────────┐
   │ Documents    │ Excel         │ Images       │ Code sandbox │ Memory      │
   │ docx pdf pptx│ formulas,     │ Pollinations │ isolated     │ BM25 search │
   │              │ charts        │ / HF FLUX    │ process      │ SQLite      │
   └──────────────┴───────────────┴──────────────┴──────────────┴─────────────┘
          │
          ▼
   Workspace per user (files you can download) + activity log
```

- **Agent loop:** the model decides which tools to call. OmniPilot runs them, shows the results back to the model, and repeats until the task is done (up to 12 steps).
- **Model router:** tries each configured provider and model in order. On a rate limit or error it moves to the next one, so free-tier chat keeps working.
- **Approvals:** risky tools (running code) **pause the agent** and show you the code. The agent resumes exactly where it stopped after you approve or deny.
- **Memory:** facts are saved per user and the relevant ones are added to every conversation. Relevance uses BM25 ranking, the classic search-engine formula.
- **Long chats:** a sliding context window keeps conversations going without hitting model limits.

## Safety

AI-written code runs in a **separate, restricted process**:

- a time limit (30s), plus memory, CPU and file-size limits
- **no API keys or secrets** in its environment
- a Python audit hook blocks **network access**, **launching programs**, and **writing or deleting outside the workspace**
- all file paths the agent uses are locked to the user's workspace, so `../../etc/passwd` is rejected

These protections are covered by automated tests. For a public multi-user deployment, also run it inside a container (Docker/gVisor).

## Quick start (free)

```bash
git clone https://github.com/VijayKrishna810680/omnipilot.git
cd omnipilot
pip install -r requirements.txt
cp .env.example .env        # add a free GROQ_API_KEY (console.groq.com, no credit card)
streamlit run app.py
pytest -q                   # 18 tests
```

**More free usage:** add several free keys (Groq, Gemini, OpenRouter). The router switches between them automatically. For **no limits at all**, run models on your own computer with [Ollama](https://ollama.com) and set `OLLAMA_URL`.

**Deploy free:** Streamlit Community Cloud → New app → this repo → `app.py` → add `GROQ_API_KEY` under Secrets.
**Docker:** `docker build -t omnipilot . && docker run -p 8501:8501 -e GROQ_API_KEY=... omnipilot`

## Project structure

| Path | Purpose |
|---|---|
| `core/agent.py` | Agent loop, tool calling, approvals and resume, context window, memory injection |
| `core/router.py` | Multi-provider model router with fallback |
| `core/tools/` | Tools: documents, Excel, images, code/projects, memory (plug-in registry with JSON schemas) |
| `core/sandbox.py` | Restricted code execution |
| `core/memory.py` | Long-term memory with BM25 search |
| `core/workspace.py` | Per-user file workspace with path safety |
| `core/activity.py` | Activity log (model and tool calls) |
| `views/` | Streamlit pages: Chat, My files, Memory, Activity |
| `tests/` | 18 tests using a scripted model: every tool, approvals, sandbox attacks, router fallback |

## Roadmap

- Web research agent with sources
- Chat with your documents (RAG)
- Scheduled automations ("every Monday, email me a report")
- Connectors through MCP (Gmail, Drive, GitHub, Slack)
- Multi-agent mode (planner, worker and reviewer)
- Model Lab: a small GPT trained from scratch

## License

MIT
