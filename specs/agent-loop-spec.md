# Spec: `run_agent()`

**File:** `agent.py`
**Status:** Partially pre-filled — complete the two blank fields before implementing

---

## Purpose

Orchestrate a single conversational turn for the Plant Advisor agent. Given a user message and the conversation history, call the LLM with available tools, execute any tool calls the LLM requests, and return the final text response.

This is the core of what makes Plant Advisor an *agent* rather than a simple chatbot: the ability to decide which tools to call, use their results to inform its response, and loop until it has everything it needs.

---

## Input / Output Contract

**Inputs:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `user_message` | `str` | The user's current message |
| `history` | `list` | Gradio conversation history — list of `[user_msg, assistant_msg]` pairs |

**Output:** `str`

The agent's final text response for this turn. Should never be empty — if something goes wrong, return a user-readable fallback message.

---

## Design Decisions

*Read `specs/system-design.md` (especially the "How the Groq Tool Calling API Works" section) before reviewing these. Complete the two blank fields before writing any code.*

---

### Messages list structure

The messages list must start with the system prompt, then replay the conversation
history, then add the new user message. Gradio history is a list of `[user, assistant]`
pairs — convert each pair to two API-format dicts:

```python
messages = [{"role": "system", "content": SYSTEM_PROMPT}]

for user_msg, assistant_msg in history:
    messages.append({"role": "user", "content": user_msg})
    if assistant_msg:
        messages.append({"role": "assistant", "content": assistant_msg})

messages.append({"role": "user", "content": user_message})
```

---

### Initial LLM call

Pass the model, the messages list, the tool definitions, and `tool_choice="auto"`
so the LLM can decide whether to call a tool or respond directly:

```python
response = client.chat.completions.create(
    model=LLM_MODEL,
    messages=messages,
    tools=TOOL_DEFINITIONS,
    tool_choice="auto",
)
```

---

### Detecting tool calls in the response

The response object has a `choices` list. Index 0 gives the assistant message.
Check its `tool_calls` attribute — if it's truthy, the LLM wants to call tools:

```python
assistant_message = response.choices[0].message

if not assistant_message.tool_calls:
    # No tool calls — LLM has a final answer
    ...
```

---

### Appending the assistant message

When there are tool calls, append the full assistant message object to `messages`
**before** appending any tool results. The API requires this ordering — a tool
result message must immediately follow the assistant message that requested it:

```python
messages.append(assistant_message)  # must come first
```

---

### Executing and appending tool results

For each tool call, extract the name and arguments, call `dispatch_tool()`, and
append the result as a `"tool"` role message. The `tool_call_id` links this result
back to the specific tool call that requested it:

```python
for tool_call in assistant_message.tool_calls:
    tool_name = tool_call.function.name
    tool_args = json.loads(tool_call.function.arguments)
    tool_result = dispatch_tool(tool_name, tool_args)

    messages.append({
        "role": "tool",
        "tool_call_id": tool_call.id,
        "content": tool_result,
    })
```

---

### Loop termination conditions

*The loop should stop when: (a) the LLM returns a response with no tool calls, OR (b) the MAX_TOOL_ROUNDS limit is reached. Describe how you will detect each condition and what you will return in each case.*

```
The loop runs inside `for round_num in range(MAX_TOOL_ROUNDS):`. On each iteration I make the LLM call and read assistant_message = response.choices[0].message.

Condition (a) - No tool calls (normal exit):
    If `not assistant_message.tool_calls` is true, the LLM has produced a final answer. I return assistant_message.content immediately from inside the loop. This is the only "successful" exit path.

Condition (b) - MAX_TOOL_ROUNDS reached (safety valve):
    If the LLM keeps requesting tools every round, the `for` loop runs out of iterations and falls through to the code AFTER the loop. There I return a user-readable fallback string (e.g. "Sorry -- I wasn't able to finish working out an answer for that. Could you rephrase or ask about one specific plant?") rather than crashing or returning.

Edge cases handled:
    - Empty content on a no-tool-call response: if assistant_message.content is None/empty, return the fallback string instead of "".
    - dispatch_tool raising or returning an empty/"not found" result: the result is still appended as a "tool" message so the LLM can react; the round cap
    prevents an infinite retry loop.
    - The function therefore always returns a non-empty string.
```

---

### Extracting the final text response

*Once the loop exits because there are no more tool calls, how do you extract the text content from the response object? What field holds the string you should return?*

```
The text lives on the assistant message of the first choice:

    response.choices[0].message.content

This is the same `assistant_message.content` I check in the no-tool-calls
branch — `assistant_message = response.choices[0].message`, then return
`assistant_message.content`. It's a plain `str` (or None if the model returned
only tool calls, which is why the no-tool-call branch is the only place I read
it for the final answer). Guard against a None/empty value by falling back to
the user-readable fallback message before returning.

```

---

## Implementation Notes

*Fill this in after implementing and testing.*

**Trace of a working agent turn (what tools were called and in what order):**

```
Query: "How should I water my monstera this time of year?"
Round 1 tool calls: lookup_plant({'plant_name': 'monstera'})  -> found: True
                    get_seasonal_conditions({})               -> spring (auto-detected)
Round 2: no tool calls -> final answer returned.
Final response: Cites the monstera's specific watering data ("top 2 inches dry,
  every 1-2 weeks") AND connects it to spring ("growing season beginning,
  increase watering frequency"). Both tools fired because the question was
  explicitly season-specific ("this time of year").
```

**What happens when you ask about a plant that isn't in the database?**

```
Query "How do I care for my bird of paradise?" -> lookup_plant returns
found: False with the not-found message. The agent acknowledges the plant
isn't in the database, offers caveated general tropical-plant guidance, and
does NOT invent specific care numbers as if it had real data. Graceful
degradation, driven mainly by the instruction embedded in the not-found
message (the lookup_plant return value), backed by the system prompt.
```

**One thing about the tool call API that surprised you:**

```
Two things:

1. No-argument tool calls don't always send "{}". For get_seasonal_conditions
   (no required params) the llama-3.3-70b model returned the arguments string
   as "null", which json.loads turns into None — not a dict. dispatch_tool then
   did None.get("season") and crashed. Fix: coerce "", "null", "{}" all to {}
   before dispatching (raw_args or "{}", then json.loads(...) or {}).

2. The model can emit a MALFORMED tool call that the API itself rejects with a
   400 "tool_use_failed" (e.g. '<function=lookup_plant[]{"plant_name":...}'
   instead of clean JSON). This happens most when a single turn asks it to look
   up many plants at once (stress-test). It's a server-side 400, not something
   you can prevent from the prompt alone — so the loop wraps the API call in
   try/except and returns the user-readable fallback instead of crashing the turn.
```

---

## Optional Challenges — Notes

**Challenge 1 — `get_plant_list()` tool:** Added a third tool (see
`tool-functions-spec.md` Function 3). "What plants do you know about?" and
"what's a good beginner plant?" both call `get_plant_list({})` once; the easy-first
sort nudges beginner recommendations.

**Challenge 2 — conversation memory:** Added a system-prompt instruction telling
the agent to treat history as memory — track which plants the user has mentioned
and connect later general questions to them. Verified: after "I just got a snake
plant", the follow-up "What should I know about watering?" (no plant named) calls
lookup_plant('snake plant') again and answers in context. The lever is the system
prompt; the history is already in the messages list.

**Challenge 3 — stress-test the loop:** Asking to compare 5 plants × 4 seasons in
one turn was the heaviest. In practice the model batches several lookups as
parallel tool calls in a single round rather than spreading them across rounds,
so it rarely reaches MAX_TOOL_ROUNDS=5 — instead it tends to hit the malformed
tool-call 400 first. When the cap *is* reached, the loop falls through and returns
the fallback string. The more common real-world failure is the malformed
generation, which the try/except now handles. Both failure modes return a
non-empty, user-readable string rather than crashing.
