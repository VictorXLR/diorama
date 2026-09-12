"""Tool-calling agent loop that builds the whiteboard incrementally.

Provider-agnostic: works with native function calling (OpenRouter, OpenAI, Ollama,
vLLM, LM Studio...) or falls back to a JSON protocol for models without tool support.
Every canvas mutation is applied server-side through :func:`apply_canvas_patch` and
streamed to the client as it happens, so a long build is visible step by step and a
late failure never discards the earlier steps.
"""

from __future__ import annotations

import copy
import json
import logging
import re
from typing import Any, AsyncIterator, Dict, List, Optional

from pydantic import ValidationError

from diorama.agents.base import (
    AgentContext,
    AgentLifecycleEvent,
    BaseAgent,
    PatchEvent,
    ResponseEvent,
    StatusEvent,
    ThoughtEvent,
)
from diorama.agents.openrouter import ChatCompletion, OpenRouterContextModel, OpenRouterError, ToolCall
from diorama.agents.prompts import build_system_prompt, build_user_prompt
from diorama.models.canvas import CanvasFile, CanvasPatch, apply_canvas_patch, changed_element_ids
from diorama.models.context import ContextVisualization
from diorama.tools import ToolContext, ToolError, ToolRegistry, ToolResult, default_registry
from diorama.visual.generator import generate_context_whiteboard_skeletons

logger = logging.getLogger("diorama.agent")

MAX_STEPS = 16
FULL_SCENE_ELEMENT_LIMIT = 60
TOOL_RESULT_CHAR_LIMIT = 12000
VISUAL_REQUEST_PATTERN = re.compile(
    r"\b(?:draw|sketch|diagram|visuali[sz]e|whiteboard|canvas|map|route|trip|travel|itinerary|"
    r"chart|timeline|flow|layout|illustrate)\b",
    re.IGNORECASE,
)
CODE_REQUEST_PATTERN = re.compile(
    r"\b(?:code|codebase|repository|repo|source(?:\s+code)?|file|files|function|class|method|module|"
    r"package|component|api|endpoint|bug|test|tests|implement|refactor|debug|compile|build|lint|commit|"
    r"branch|dependenc(?:y|ies)|import|export)\b",
    re.IGNORECASE,
)
NON_CODE_SCENE_OVERVIEW_LIMIT = 36


class ToolLoopAgent(BaseAgent):
    """Runs the model in a tool loop until it calls ``finish`` (or answers in plain text)."""

    def __init__(
        self,
        model: Optional[OpenRouterContextModel] = None,
        registry: Optional[ToolRegistry] = None,
        *,
        max_steps: int = MAX_STEPS,
    ) -> None:
        super().__init__(
            agent_id="diorama-whiteboard-agent",
            name="Diorama Whiteboard Agent",
            description="Builds and edits the shared Excalidraw board through composable tools.",
        )
        self.model = model or OpenRouterContextModel()
        self.registry = registry or default_registry(include_code=False)
        self.code_registry = registry or default_registry(include_code=True)
        self.max_steps = max_steps

    # ------------------------------------------------------------------ main loop

    async def process_user_input(
        self,
        input_text: str,
        context: AgentContext,
    ) -> AsyncIterator[AgentLifecycleEvent]:
        if not self.model.is_configured:
            raise OpenRouterError(
                "No model is configured. Set OPENROUTER_API_KEY, or DIORAMA_LLM_BASE_URL for a local model."
            )

        yield StatusEvent(status="thinking", stage_description="Reading the request and the current board...")

        tool_context = ToolContext(
            session_id=context.session_id,
            scene=copy.deepcopy(context.visual_elements),
            files=dict(context.files),
            theme=context.theme,
            selected_element_ids=list(context.selected_element_ids),
            viewport=context.viewport,
            workspace_context=dict(context.workspace_context or {}),
            workspace=context.workspace,
        )
        original_scene = context.visual_elements
        native_tools = self.model.native_tools
        # A workspace may be attached while the user asks for a completely
        # unrelated map, trip, or diagram.  Keep those turns on the lean
        # visual-agent contract that existed before codebase mode was added;
        # exposing code tools and a huge repo overview made ordinary drawing
        # requests needlessly unreliable.
        use_code_tools = context.workspace is not None and self._requires_code_tools(input_text)
        registry = self.code_registry if use_code_tools else self.registry
        full_scene = len(context.visual_elements) <= FULL_SCENE_ELEMENT_LIMIT
        scene_overview_limit = (
            NON_CODE_SCENE_OVERVIEW_LIMIT if context.workspace is not None and not use_code_tools else None
        )
        messages: List[Dict[str, Any]] = [
            {
                "role": "system",
                "content": build_system_prompt(
                    context,
                    registry,
                    native_tools=native_tools,
                    include_code_instructions=use_code_tools,
                ),
            },
            {
                "role": "user",
                "content": build_user_prompt(
                    input_text,
                    context,
                    full_scene=full_scene,
                    include_workspace_context=use_code_tools,
                    scene_overview_limit=scene_overview_limit,
                ),
            },
        ]
        tool_schemas = registry.schemas()
        # A chat-only acknowledgement such as "keep this" should be allowed to
        # finish without a drawing.  Requests that explicitly ask for a visual,
        # however, must not be able to terminate through a bare native `finish`
        # call.  Several providers prefer that shortcut even when tools are
        # available, which used to leave the board unchanged.
        requires_visual_update = self._requires_visual_update(input_text)
        touched: List[str] = []
        new_files: Dict[str, CanvasFile] = {}
        summaries: List[str] = []
        finished: Optional[Dict[str, Any]] = None

        for step in range(self.max_steps):
            yield StatusEvent(
                status="generating_plan" if step == 0 else "analyzing_context",
                stage_description="Planning the drawing..." if step == 0 else f"Deciding the next step ({step + 1})...",
            )
            completion = await self.model.complete(messages, tools=tool_schemas, json_mode=not native_tools)

            calls = list(completion.tool_calls)
            content = completion.content or ""
            if not calls and content.strip():
                parsed = self._parse_json_reply(content)
                if parsed is not None:
                    fallback_calls = self._calls_from_json(parsed)
                    if fallback_calls:
                        calls = fallback_calls
                    else:
                        finished = await self._finish_from_json(
                            parsed, tool_context, touched, new_files, summaries, current_context=context.current_context
                        )
                        if finished is not None:
                            if (
                                requires_visual_update
                                and not finished.get("questions")
                                and not changed_element_ids(original_scene, tool_context.scene)
                            ):
                                # Some providers answer a native-tools request
                                # with the JSON fallback's `final` shape.  It
                                # must obey the same visual-update contract as
                                # a native `finish` call.
                                messages.append({"role": "assistant", "content": content})
                                messages.append(
                                    {
                                        "role": "user",
                                        "content": (
                                            "Do not finish a visual request with an unchanged board. "
                                            "Use the appropriate visual tool(s), update Excalidraw, then finish."
                                        ),
                                    }
                                )
                                finished = None
                                continue
                            break
                elif completion.truncated or self._looks_like_json(content):
                    raise OpenRouterError(
                        "The model's response was cut off or malformed before it finished. "
                        "Try a simpler request or split it up."
                    )
                else:
                    # A prose-only answer leaves the board stale.  Give the
                    # model its wording back as context, then require an
                    # actual canvas/tool result.  This matters especially for
                    # travel requests, where a helpful textual itinerary is
                    # otherwise easy to produce without calling fetch_map.
                    messages.append({"role": "assistant", "content": content})
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                "Do not answer in prose only. Use the appropriate visual tool(s), update the "
                                "Excalidraw board, then call finish. For trips or places, fetch a real map first."
                            ),
                        }
                    )
                    continue
            if not calls:
                if completion.truncated:
                    raise OpenRouterError("The model ran out of room mid-step. Try a simpler request or split it up.")
                # Nudge once; an empty completion is usually transient.
                messages.append({"role": "assistant", "content": content or ""})
                messages.append({"role": "user", "content": "Continue: call a tool, or call finish when done."})
                continue

            messages.append(self._assistant_message(completion, calls, native_tools))

            fallback_results: List[Dict[str, Any]] = []
            rejected_finish = False
            for call in calls:
                yield ThoughtEvent(
                    thought=self._describe_call(call),
                    tool=call.name,
                    arguments=self._compact_args(call.arguments),
                )
                yield StatusEvent(status="calling_tool", stage_description=f"Running {call.name}...")

                files_before = len(tool_context.file_changes)
                result, error = await self._run_tool(call, tool_context, registry)
                for change in tool_context.file_changes[files_before:]:
                    yield ThoughtEvent(
                        thought=f"Edited {change['path']}",
                        tool="file_edit",
                        arguments={"path": change["path"], "diff": (change.get("diff") or "")[:1500]},
                    )
                if result is not None and result.patch is not None:
                    before = tool_context.scene
                    try:
                        after = apply_canvas_patch(
                            before, result.patch, theme=tool_context.theme, known_files=tool_context.known_file_ids
                        )
                    except ValueError as exc:
                        error = f"Canvas patch rejected: {exc}"
                        result = None
                    else:
                        tool_context.scene = after
                        for file_id, file in result.patch.files.items():
                            tool_context.files[file_id] = file
                            new_files[file_id] = file
                        changed = changed_element_ids(before, after)
                        touched.extend(changed)
                        if result.summary:
                            summaries.append(result.summary)
                        yield StatusEvent(status="syncing_whiteboard", stage_description=result.summary or "Updating the board...")
                        yield PatchEvent(
                            visual_elements=after,
                            files=dict(result.patch.files),
                            changed_element_ids=changed,
                            summary=result.summary,
                        )

                if error is not None:
                    payload: Any = {"error": error}
                    yield ThoughtEvent(thought=f"{call.name} failed: {error}", tool=call.name)
                elif result is not None:
                    payload = result.content
                else:  # pragma: no cover - defensive
                    payload = {"error": "Tool produced no result."}

                if result is not None and result.final:
                    if (
                        call.name == "finish"
                        and requires_visual_update
                        and not changed_element_ids(original_scene, tool_context.scene)
                    ):
                        # Send a normal tool error back to the model rather than
                        # accepting a final answer with an unchanged board.  This
                        # keeps the native OpenAI tool-call transcript valid and
                        # lets the next completion choose `draw`, `fetch_map`, or
                        # `edit_elements` before trying to finish again.
                        error = (
                            "finish was rejected because this visual request has not changed the Excalidraw board. "
                            "Make a visible canvas update before calling finish."
                        )
                        result = None
                        payload = {"error": error}
                        yield ThoughtEvent(thought=f"{call.name} failed: {error}", tool=call.name)
                        rejected_finish = True
                    else:
                        finished = self._finalize(result.content)
                        break

                text = json.dumps(payload, ensure_ascii=False, default=str)
                if len(text) > TOOL_RESULT_CHAR_LIMIT:
                    text = text[:TOOL_RESULT_CHAR_LIMIT] + '... (truncated)"}'
                if native_tools:
                    messages.append({"role": "tool", "tool_call_id": call.id, "name": call.name, "content": text})
                else:
                    fallback_results.append({"name": call.name, "result": payload})

            if finished is not None:
                break
            if rejected_finish:
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "The previous finish was rejected because the Excalidraw scene is unchanged. "
                            "Make a visible board update with draw, edit_elements, or an asset placement, "
                            "then call finish again."
                        ),
                    }
                )
            if not native_tools:
                text = json.dumps({"toolResults": fallback_results}, ensure_ascii=False, default=str)
                if len(text) > TOOL_RESULT_CHAR_LIMIT * 2:
                    text = text[: TOOL_RESULT_CHAR_LIMIT * 2] + "... (truncated)"
                messages.append({"role": "user", "content": text})

        if finished is None:
            if touched:
                finished = {
                    "reply": "I made the changes above but ran out of steps before wrapping up. Tell me what to refine next.",
                    "summary": "; ".join(summaries[-3:]) or "Updated the board.",
                    "suggestions": [],
                    "questions": [],
                }
            else:
                raise OpenRouterError("The model did not produce a result within the step limit.")

        yield StatusEvent(status="generating_visual", stage_description="Wrapping up...")
        existing_ids = {element["id"] for element in original_scene}
        response_context = finished.get("context", context.current_context)
        yield ResponseEvent(
            reply_text=finished["reply"],
            visual_elements=tool_context.scene,
            files=new_files,
            changed_element_ids=list(dict.fromkeys(touched)),
            visual_summary=finished.get("summary") or ("; ".join(summaries[-3:]) if summaries else ""),
            elements_added=sum(element["id"] not in existing_ids for element in tool_context.scene),
            suggestions=finished.get("suggestions", []),
            questions=finished.get("questions", []),
            file_changes=tool_context.file_changes,
            context=response_context,
        )

    # ------------------------------------------------------------------ helpers

    async def _run_tool(
        self, call: ToolCall, tool_context: ToolContext, registry: ToolRegistry
    ) -> tuple[Optional[ToolResult], Optional[str]]:
        tool = registry.get(call.name)
        if tool is None:
            return None, f"Unknown tool '{call.name}'. Available: {', '.join(t.name for t in registry)}."
        try:
            return await tool.run(call.arguments, tool_context), None
        except ToolError as exc:
            return None, str(exc)
        except Exception as exc:  # noqa: BLE001 - never let one tool kill the turn
            logger.exception("Tool %s crashed", call.name)
            return None, f"{call.name} crashed: {exc.__class__.__name__}: {exc}"

    @staticmethod
    def _assistant_message(completion: ChatCompletion, calls: List[ToolCall], native_tools: bool) -> Dict[str, Any]:
        if native_tools and completion.raw_message.get("tool_calls"):
            message = {"role": "assistant", "content": completion.content, "tool_calls": completion.raw_message["tool_calls"]}
            return message
        if native_tools:
            # JSON-fallback calls emitted by a model in native mode: re-encode as tool_calls for continuity.
            return {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": json.dumps(c.arguments)}}
                    for c in calls
                ],
            }
        return {"role": "assistant", "content": completion.content or ""}

    @staticmethod
    def _looks_like_json(content: str) -> bool:
        stripped = content.strip()
        return stripped.startswith("{") or stripped.startswith("```")

    @staticmethod
    def _requires_visual_update(input_text: str) -> bool:
        """Whether a request explicitly asks the agent to change the board.

        The agent also supports conversational acknowledgements and code-only
        turns, so this intentionally keys off clear visual language rather than
        requiring a canvas patch for every response.
        """
        return bool(VISUAL_REQUEST_PATTERN.search(input_text))

    @staticmethod
    def _requires_code_tools(input_text: str) -> bool:
        """Only expose repository tools when the user's request is code-oriented."""
        return bool(CODE_REQUEST_PATTERN.search(input_text))

    @staticmethod
    def _parse_json_reply(content: str) -> Optional[Any]:
        stripped = content.strip()
        fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", stripped, flags=re.DOTALL | re.IGNORECASE)
        if fenced:
            stripped = fenced.group(1)
        if not stripped.startswith("{"):
            return None
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _calls_from_json(data: Any) -> List[ToolCall]:
        if not isinstance(data, dict):
            return []
        raw_calls = data.get("toolCalls") or data.get("tool_calls")
        if not isinstance(raw_calls, list):
            return []
        calls = []
        for index, item in enumerate(raw_calls):
            if not isinstance(item, dict) or not isinstance(item.get("name"), str):
                continue
            arguments = item.get("arguments")
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    arguments = {"__invalid_json__": arguments}
            calls.append(ToolCall(id=f"json_{index}", name=item["name"], arguments=arguments if isinstance(arguments, dict) else {}))
        return calls

    async def _finish_from_json(
        self,
        data: Any,
        tool_context: ToolContext,
        touched: List[str],
        new_files: Dict[str, CanvasFile],
        summaries: List[str],
        *,
        current_context: Optional[ContextVisualization],
    ) -> Optional[Dict[str, Any]]:
        """Accept final answers in JSON form, including the legacy one-shot ``canvas`` patch format."""
        if not isinstance(data, dict):
            return None
        if isinstance(data.get("question"), str):
            options = data.get("options")
            return {
                "reply": data["question"].strip(),
                "summary": "",
                "suggestions": [],
                "questions": [o for o in options if isinstance(o, str)] if isinstance(options, list) else [],
            }
        final = data.get("final") if isinstance(data.get("final"), dict) else data
        legacy_context = self._legacy_context(data, current_context)
        if legacy_context is not None:
            # Older Diorama clients describe a complete visual context instead
            # of issuing draw calls.  Keep that useful contract: turn it into
            # the same Excalidraw skeleton scene the preset flow uses.
            before = tool_context.scene
            tool_context.scene = generate_context_whiteboard_skeletons(legacy_context)
            touched.extend(changed_element_ids(before, tool_context.scene))
        if "canvas" in data:
            try:
                patch = CanvasPatch.model_validate(data["canvas"])
                after = apply_canvas_patch(
                    tool_context.scene, patch, theme=tool_context.theme, known_files=tool_context.known_file_ids
                )
            except (ValidationError, ValueError) as exc:
                raise OpenRouterError(f"The model returned an invalid canvas patch: {exc}") from exc
            touched.extend(changed_element_ids(tool_context.scene, after))
            tool_context.scene = after
            for file_id, file in patch.files.items():
                tool_context.files[file_id] = file
                new_files[file_id] = file
        reply = final.get("reply")
        if not isinstance(reply, str) or not reply.strip():
            if "canvas" in data:
                reply = "Updated the board."
            else:
                return None
        summary = final.get("summary") if isinstance(final.get("summary"), str) else ""
        if summary:
            summaries.append(summary)
        finished = self._finalize({"reply": reply, "summary": summary, "suggestions": final.get("suggestions")})
        if legacy_context is not None:
            finished["context"] = legacy_context
        return finished

    def _legacy_context(
        self, data: Dict[str, Any], current_context: Optional[ContextVisualization]
    ) -> Optional[ContextVisualization]:
        """Validate a legacy ``context`` response and merge it with the current description."""
        raw_context = data.get("context")
        if not isinstance(raw_context, dict):
            return None
        payload: Dict[str, Any] = {}
        # The model may send a partial update for a context already on the
        # board; the original structured-analysis API supported that shape.
        if current_context is not None:
            payload.update(current_context.model_dump(by_alias=True))
        payload.update(raw_context)
        try:
            visual_context = ContextVisualization.model_validate(payload)
        except ValidationError as exc:
            raise OpenRouterError("The model returned a visual context that does not match Diorama's schema.") from exc
        return self.model._normalize_context(visual_context)

    @staticmethod
    def _finalize(content: Any) -> Dict[str, Any]:
        data = content if isinstance(content, dict) else {}
        suggestions = data.get("suggestions")
        questions = data.get("questions")
        return {
            "reply": str(data.get("reply") or "Done.").strip(),
            "summary": str(data.get("summary") or "").strip(),
            "suggestions": [s.strip() for s in suggestions if isinstance(s, str) and s.strip()][:4]
            if isinstance(suggestions, list)
            else [],
            "questions": [q.strip() for q in questions if isinstance(q, str) and q.strip()][:4]
            if isinstance(questions, list)
            else [],
        }

    @staticmethod
    def _describe_call(call: ToolCall) -> str:
        args = call.arguments
        if call.name == "draw" and isinstance(args.get("primitives"), list):
            kinds: Dict[str, int] = {}
            for item in args["primitives"]:
                if isinstance(item, dict):
                    kinds[str(item.get("kind"))] = kinds.get(str(item.get("kind")), 0) + 1
            parts = ", ".join(f"{count} {kind}" for kind, count in kinds.items())
            return f"Drawing {parts or 'primitives'}"
        if call.name == "fetch_map" and isinstance(args.get("markers"), list):
            names = [m.get("name") for m in args["markers"] if isinstance(m, dict)]
            return "Fetching a map of " + ", ".join(str(n) for n in names[:5]) + ("…" if len(names) > 5 else "")
        if call.name == "finish":
            return "Wrapping up"
        if call.name == "ask_user":
            return "Asking a clarifying question"
        if call.name == "inspect_scene":
            return "Looking at what is on the board"
        return f"Calling {call.name}"

    @staticmethod
    def _compact_args(arguments: Dict[str, Any], limit: int = 600) -> Dict[str, Any]:
        text = json.dumps(arguments, ensure_ascii=False, default=str)
        if len(text) <= limit:
            return arguments
        return {"_preview": text[:limit] + "…"}
