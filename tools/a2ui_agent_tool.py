"""A2UI Agent tool — generates structured UI JSON from natural language prompts."""

import json
import logging
import os
import uuid

from tools.registry import registry, tool_error

logger = logging.getLogger(__name__)

# ── ADK agent runner (in-process, no web server needed) ──────────────────────

def _run_adk_agent(prompt: str) -> str:
    """Run the A2UI restaurant agent and return the raw response text."""
    import google.adk.agents.llm_agent as llm_agent
    from google.adk.runners import InMemoryRunner
    from google.adk.tools.tool_context import ToolContext
    from google.genai import types

    from a2ui.schema.constants import VERSION_0_8
    from a2ui.schema.manager import A2uiSchemaManager
    from a2ui.basic_catalog.provider import BasicCatalog

    # ── Tool: get restaurants ──
    def get_restaurants(tool_context: ToolContext) -> str:
        """Call this tool to get a list of restaurants."""
        return json.dumps([
            {
                "name": "Xi'an Famous Foods",
                "detail": "Spicy and savory hand-pulled noodles.",
                "imageUrl": "http://localhost:10002/static/shrimpchowmein.jpeg",
                "rating": "★★★★☆",
                "infoLink": "[More Info](https://www.xianfoods.com/)",
                "address": "81 St Marks Pl, New York, NY 10003"
            },
            {
                "name": "Han Dynasty",
                "detail": "Authentic Szechuan cuisine.",
                "imageUrl": "http://localhost:10002/static/mapotofu.jpeg",
                "rating": "★★★★☆",
                "infoLink": "[More Info](https://www.handynasty.net/)",
                "address": "90 3rd Ave, New York, NY 10003"
            },
            {
                "name": "RedFarm",
                "detail": "Modern Chinese with a farm-to-table approach.",
                "imageUrl": "http://localhost:10002/static/beefbroccoli.jpeg",
                "rating": "★★★★☆",
                "infoLink": "[More Info](https://www.redfarmnyc.com/)",
                "address": "529 Hudson St, New York, NY 10014"
            },
        ])

    # ── Schema + prompt generation ──
    examples_path = "/home/hermes/hermes-workspace/a2ui-examples/0.8"
    schema_manager = A2uiSchemaManager(
        version=VERSION_0_8,
        catalogs=[BasicCatalog.get_config(version=VERSION_0_8, examples_path=examples_path)],
    )

    role_description = (
        "You are a helpful restaurant finding assistant. "
        "Your final output MUST be a a2ui UI JSON response."
    )
    ui_description = """
- If the query is for a list of restaurants, use the restaurant data from the `get_restaurants` tool to populate `dataModelUpdate.contents`.
- If 5 or fewer restaurants, use `SINGLE_COLUMN_LIST_EXAMPLE` template.
- If more than 5, use `TWO_COLUMN_LIST_EXAMPLE` template.
- If the query is to book a restaurant, use `BOOKING_FORM_EXAMPLE` template.
- If the query is a booking submission, use `CONFIRMATION_EXAMPLE` template.
"""
    instruction = schema_manager.generate_system_prompt(
        role_description=role_description,
        ui_description=ui_description,
        include_schema=True,
        include_examples=True,
        validate_examples=True,
    )

    # ── Build agent + runner ──
    agent = llm_agent.Agent(
        model="gemini-2.5-flash",
        name="restaurant_agent",
        description="An agent that finds restaurants and helps book tables.",
        instruction=instruction,
        tools=[get_restaurants],
    )

    runner = InMemoryRunner(agent=agent, app_name="a2ui_tool")
    session_id = str(uuid.uuid4())

    # ── Run ──
    content = types.Content(role="user", parts=[types.Part(text=prompt)])
    events = runner.run(
        user_id="hermes_tool",
        session_id=session_id,
        new_message=content,
    )

    # Collect final text response
    final_text = ""
    for event in events:
        if hasattr(event, "content") and event.content:
            for part in event.content.parts:
                if hasattr(part, "text") and part.text:
                    final_text += part.text

    return final_text


# ── Extract A2UI JSON from response ──────────────────────────────────────────

def _extract_a2ui_json(text: str) -> list:
    """Extract A2UI JSON blocks from the agent response."""
    import re

    # Try <a2ui-json> tags first
    blocks = re.findall(r"<a2ui-json>(.*?)</a2ui-json>", text, re.DOTALL)
    if blocks:
        results = []
        for block in blocks:
            try:
                results.append(json.loads(block.strip()))
            except json.JSONDecodeError:
                continue
        if results:
            return results

    # Fallback: try to parse the whole thing as JSON
    try:
        return [json.loads(text.strip())]
    except json.JSONDecodeError:
        pass

    # Fallback: find any JSON array in the text
    matches = re.findall(r"\[[\s\S]*?\]", text)
    for m in matches:
        try:
            parsed = json.loads(m)
            if isinstance(parsed, list) and len(parsed) > 0:
                return [parsed]
        except json.JSONDecodeError:
            continue

    return []


# ── Handler ──────────────────────────────────────────────────────────────────

def handle_a2ui_agent(args: dict, **kwargs) -> str:
    """Generate A2UI JSON from a natural language prompt."""
    prompt = args.get("prompt", "")
    if not prompt:
        return tool_error("Missing required parameter: prompt")

    format_type = args.get("format", "json")  # json | summary | both

    try:
        raw_response = _run_adk_agent(prompt)
    except Exception as e:
        return tool_error(f"ADK agent failed: {e}")

    a2ui_blocks = _extract_a2ui_json(raw_response)

    if format_type == "summary":
        return _summarize_a2ui(a2ui_blocks)

    result = {
        "status": "ok",
        "raw_response": raw_response[:5000],
        "a2ui_blocks": len(a2ui_blocks),
        "a2ui_json": a2ui_blocks,
    }

    if format_type == "both":
        result["summary"] = _summarize_a2ui(a2ui_blocks)

    return json.dumps(result, indent=2, ensure_ascii=False)


def _summarize_a2ui(blocks: list) -> str:
    """Create a human-readable summary of A2UI blocks."""
    lines = []
    for i, block in enumerate(blocks):
        if isinstance(block, list):
            for msg in block:
                if "surfaceUpdate" in msg:
                    su = msg["surfaceUpdate"]
                    comps = su.get("components", [])
                    lines.append(f"Surface '{su.get('surfaceId', '?')}': {len(comps)} components")
                elif "dataModelUpdate" in msg:
                    dm = msg["dataModelUpdate"]
                    contents = dm.get("contents", [])
                    lines.append(f"Data for '{dm.get('surfaceId', '?')}': {len(contents)} entries")
                    for entry in contents[:5]:
                        key = entry.get("key", "?")
                        val = entry.get("valueString", entry.get("valueNumber", ""))
                        lines.append(f"  • {key}: {val}")
                elif "beginRendering" in msg:
                    br = msg["beginRendering"]
                    lines.append(f"Render: surface='{br.get('surfaceId', '?')}', root='{br.get('root', '?')}'")
        elif isinstance(block, dict):
            lines.append(f"Block {i}: {list(block.keys())[:3]}")
    return "\n".join(lines) if lines else "No A2UI content found"


# ── Schema ───────────────────────────────────────────────────────────────────

A2UI_AGENT_SCHEMA = {
    "type": "object",
    "properties": {
        "prompt": {
            "type": "string",
            "description": "Natural language prompt describing what UI to generate (e.g., 'find me restaurants in NYC')"
        },
        "format": {
            "type": "string",
            "enum": ["json", "summary", "both"],
            "description": "Output format: 'json' for raw A2UI JSON, 'summary' for text description, 'both' for both",
            "default": "both"
        }
    },
    "required": ["prompt"]
}


def _check_a2ui_requirements() -> bool:
    """Check that google-adk and a2ui-agent-sdk are installed."""
    try:
        import google.adk
        import a2ui
        return True
    except ImportError:
        return False


# ── Register ─────────────────────────────────────────────────────────────────

registry.register(
    name="a2ui_agent",
    toolset="image_gen",
    schema=A2UI_AGENT_SCHEMA,
    handler=handle_a2ui_agent,
    check_fn=_check_a2ui_requirements,
    description="Generate structured A2UI JSON (cards, lists, forms) from natural language using Google ADK + Gemini",
    emoji="🎨",
)
