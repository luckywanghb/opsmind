"""Minimal kernel prompt contracts.

These prompts define node boundaries only.  They intentionally do not encode
Golden Cases, business SOPs, tool instructions, or provider details.
"""

REQUEST_UNDERSTANDING_SYSTEM_PROMPT = (
    "Understand the user's request using the supplied context. "
    "Return only RequestUnderstandingOutput fields "
    "(primary_intent, request_type, symptom, entities, risk_signal, "
    "uncertainty); do not answer the user or choose an action."
)

ACTION_DECISION_SYSTEM_PROMPT = (
    "Choose the next Agent action from the supplied request and compact state "
    "context. Return only ActionDecisionOutput fields (action, goal, "
    "rationale)."
)

# Short aliases make the prompt boundary discoverable without duplicating text.
REQUEST_UNDERSTANDING_PROMPT = REQUEST_UNDERSTANDING_SYSTEM_PROMPT
ACTION_DECISION_PROMPT = ACTION_DECISION_SYSTEM_PROMPT
