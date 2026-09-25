"""Tools that let the agent save and look up long-term memories."""
from core.tools.registry import ToolResult, tool


@tool("remember",
      "Save an important long-term fact or preference about the user (name, role, preferences, "
      "project details) so it is available in future chats. Keep it short and factual.",
      {"fact": {"type": "string"}}, ["fact"])
def remember(ctx, fact):
    fid = ctx.memory.add(fact)
    return ToolResult(True, f"Saved to memory (#{fid}): {fact}")


@tool("recall", "Search long-term memory for facts related to a query.",
      {"query": {"type": "string"}}, ["query"])
def recall(ctx, query):
    hits = ctx.memory.search(query)
    return ToolResult(True, "\n".join(f"- {h}" for h in hits) or "Nothing relevant in memory.")
