"""Demo SF hook: per-session REPLSession in state + sf_eval tool for the LLM."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from republic import ToolContext

from bub.framework import BubFramework
from bub.hookspecs import hookimpl
from bub.tools import tool
from bub.types import Envelope, State

from bub_sf.bub_ext import BubExt
from bub_sf.bub_ext import BubExt
from systemf.elab3.repl import REPL
from systemf.elab3.repl_session import REPLSession
from systemf.elab3.types.protocols import Ext
from systemf.elab3.val_pp import pp_val

# ---------------------------------------------------------------------------
# Tool — module-level @tool auto-registers into REGISTRY on import.
# ---------------------------------------------------------------------------


@tool(
    context=True,
    description=(
        "Evaluate a System F expression in the current REPL session. "
        "Returns the pretty-printed value and type, or an error message."
    ),
)
def sf_eval(expr: str, context: ToolContext) -> str:
    sf_hook: SFHookImpl | None = context.state.get("sf_ctx")

    # session is either created for root or preset for nested calls
    session_id: str | None = context.state.get("sf_session_id")
    session: REPLSession | None = context.state.get("sf_session")
    if session is None and sf_hook and session_id:
        session = sf_hook._get_or_create(session_id)
    
    if session is None:
        return "Error: no REPL session attached to this conversation"
    try:
        result = session.eval(expr)
    except Exception as exc:
        return f"Error: {exc}"
    if result is None:
        return "(no value — definition accepted)"
    val, ty = result
    return pp_val(session, val, ty)


# ---------------------------------------------------------------------------
# Hook implementation — register as a bub entry point:
#
#   [project.entry-points.bub]
#   sf = "bub_sf.sf_hook:SFHookImpl"
# ---------------------------------------------------------------------------


class SFHookImpl:
    """Wires a per-session REPLSession into framework state and exposes sf_eval."""

    def __init__(self, framework: BubFramework) -> None:
        # The module-level @tool already ran when Python imported this module,
        # so sf_eval is already registered — no extra import needed.
        self.framework = framework
        sf_exts: list[Ext] = []
        sf_exts.append(BubExt(framework))
        self._repl = REPL(
            search_paths=[str(Path(__file__).parent.resolve())],
            exts=sf_exts
        )
        self._sessions: dict[str, REPLSession] = {}

    def _get_or_create(self, session_id: str) -> REPLSession:
        if session_id not in self._sessions:
            self._sessions[session_id] = self._repl.new_session()
        return self._sessions[session_id]

    @hookimpl
    async def load_state(self, message: Envelope, session_id: str) -> State:
        """Populate state with a persistent REPLSession for this conversation."""
        return {
            "sf_session_id": session_id,
            "sf_ctx": self,
        }

    @hookimpl
    def system_prompt(self, prompt: str | list[dict], state: State) -> str:
        """Tell the LLM it has a System F REPL available via sf_eval."""
        return (
            "You have access to a live System F type-checker and evaluator.\n" +
            "Use the `sf_eval` tool to evaluate or type-check System F expressions.\n" +
            "The REPL session persists across turns — definitions accumulate."
        )
