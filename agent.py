import json
from groq import Groq
from config import GROQ_API_KEY, LLM_MODEL, MAX_TOOL_ROUNDS
from tools import lookup_plant, get_seasonal_conditions, get_plant_list

_client = Groq(api_key=GROQ_API_KEY)

# ──────────────────────────────────────────────
# Tool definitions
#
# These are the schemas that tell the LLM what tools are available and how to
# call them. The LLM reads these descriptions and decides when (and how) to use
# each tool. They're already complete — your job is to implement the tool
# functions in tools.py and the agent loop below.
# ──────────────────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "lookup_plant",
            "description": (
                "Look up care information for a specific houseplant by name. "
                "Returns detailed watering, light, humidity, and temperature requirements. "
                "Use this whenever the user asks about a specific plant."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "plant_name": {
                        "type": "string",
                        "description": "The plant name to look up. Can be a common name, scientific name, or nickname (e.g., 'pothos', 'devil's ivy', 'Monstera deliciosa').",
                    }
                },
                "required": ["plant_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_seasonal_conditions",
            "description": (
                "Get seasonal care adjustments for houseplants. "
                "Returns guidance on watering, fertilizing, light, and pests for the current or specified season. "
                "Use this when a user asks a season-specific question, or to complement plant care advice with seasonal context."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "season": {
                        "type": "string",
                        "description": "The season to get care conditions for. If omitted, the current season is detected automatically.",
                        "enum": ["spring", "summer", "fall", "winter"],
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_plant_list",
            "description": (
                "List every plant in the care database with its name and difficulty level. "
                "Takes no arguments. Use this for catalog or attribute questions that aren't about "
                "one named plant — e.g. 'what plants do you know about?', 'what's a good beginner plant?', "
                "or 'which plants are easy to care for?'. After listing, you can call lookup_plant for "
                "details on whichever plant the user chooses."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
]

# ──────────────────────────────────────────────
# System prompt
# ──────────────────────────────────────────────

SYSTEM_PROMPT = (
    "You are a knowledgeable and friendly plant care advisor. "
    "Help users care for their houseplants by looking up specific plant information "
    "and current seasonal conditions using your available tools.\n\n"
    "Always use your tools to look up plant-specific information before answering — "
    "don't rely on your general knowledge alone. If a plant isn't in your database, "
    "say so clearly and offer general guidance based on what the user describes.\n\n"
    "Keep your advice practical and specific. Cite the source of your information "
    "when you have it (e.g., 'According to the care data for your monstera...').\n\n"
    "Use the conversation history as memory: keep track of which plants the user "
    "has told you they own. When a later question is general (e.g. 'how often "
    "should I water?') and the user has mentioned a specific plant earlier, "
    "connect the two proactively — e.g. 'Since you mentioned you have a pothos, "
    "...' — and look that plant up again rather than answering generically. Do "
    "not invent plants the user never mentioned."
)

# ──────────────────────────────────────────────
# Tool dispatch
#
# This is already complete. It routes tool calls from the LLM to the actual
# Python functions in tools.py, and returns results as JSON strings (which is
# what the Groq API expects for tool results).
# ──────────────────────────────────────────────

def dispatch_tool(tool_name: str, tool_args: dict) -> str:
    """Route a tool call to the correct function and return the result as a JSON string."""
    print(f"  → Tool call: {tool_name}({tool_args})")
    if tool_name == "lookup_plant":
        result = lookup_plant(tool_args["plant_name"])
    elif tool_name == "get_seasonal_conditions":
        result = get_seasonal_conditions(tool_args.get("season"))
    elif tool_name == "get_plant_list":
        result = get_plant_list()
    else:
        result = {"error": f"Unknown tool: {tool_name}"}
    print(f"  ← Result: {json.dumps(result)[:120]}{'...' if len(json.dumps(result)) > 120 else ''}")
    return json.dumps(result)


# ──────────────────────────────────────────────
# Agent loop
# ──────────────────────────────────────────────

def run_agent(user_message: str, history: list) -> str:
    """
    Run the plant care agent for one user turn and return its response.

    The agent loop follows the pattern documented in specs/agent-loop-spec.md.

    The loop works like this:
      1. Build a messages list: system prompt + conversation history + new user message
      2. Call the LLM with messages and TOOL_DEFINITIONS
      3. If the response contains tool_calls:
           a. Append the assistant message (with tool_calls) to messages
           b. For each tool call: execute via dispatch_tool(), append the result
           c. Call the LLM again with the updated messages
           d. Repeat until no more tool_calls (or MAX_TOOL_ROUNDS is reached)
      4. Return the final text response

    Key details to get right:
      - The assistant message must be appended BEFORE tool results
      - Tool result messages use role="tool" with a tool_call_id field
      - Append the assistant's message object directly (not just its content)
      - The history format from Gradio: list of [user_message, assistant_message] pairs
    """
    FALLBACK = (
        "Sorry — I wasn't able to finish working out an answer for that. "
        "Could you rephrase, or ask about one specific plant?"
    )

    # 1. Build the messages list: system prompt + history + new user message.
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for user_msg, assistant_msg in history:
        messages.append({"role": "user", "content": user_msg})
        if assistant_msg:
            messages.append({"role": "assistant", "content": assistant_msg})
    messages.append({"role": "user", "content": user_message})

    # 2. Tool-calling loop, bounded by MAX_TOOL_ROUNDS (the safety valve).
    for _ in range(MAX_TOOL_ROUNDS):
        try:
            response = _client.chat.completions.create(
                model=LLM_MODEL,
                messages=messages,
                tools=TOOL_DEFINITIONS,
                tool_choice="auto",
            )
        except Exception as exc:
            # The model occasionally emits a malformed tool call that the API
            # rejects (400 tool_use_failed), or the network/API call fails.
            # Degrade gracefully instead of crashing the whole turn.
            print(f"  ! LLM call failed: {exc}")
            return FALLBACK
        assistant_message = response.choices[0].message

        # Condition (a): no tool calls — the LLM has a final answer.
        if not assistant_message.tool_calls:
            return assistant_message.content or FALLBACK

        # The assistant message (with tool_calls) MUST be appended before results.
        messages.append(assistant_message)

        # Execute each tool call and append its result as a "tool" message.
        for tool_call in assistant_message.tool_calls:
            tool_name = tool_call.function.name
            # Arguments come back as a JSON string. For a no-arg call the model
            # may send "", "null", or "{}" — coerce all of these to an empty dict.
            raw_args = tool_call.function.arguments or "{}"
            tool_args = json.loads(raw_args) or {}
            tool_result = dispatch_tool(tool_name, tool_args)
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": tool_result,
            })

    # Condition (b): MAX_TOOL_ROUNDS reached without a final answer.
    return FALLBACK
