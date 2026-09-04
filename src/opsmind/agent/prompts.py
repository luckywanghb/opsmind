"""Provider-neutral prompt contracts for the model-driven Agent loop.

These prompts define node boundaries only.  They intentionally do not encode
Golden Cases, business SOPs, or provider details.  Tool descriptions are
inserted at runtime from the registry so adding a capability does not require
semantic routing changes in Python.
"""

from __future__ import annotations


def language_instruction(query: str | None) -> str:
    """Return the hard natural-language contract for the user's input.

    This is a language-format instruction, not business routing.  Machine
    enums, tool names and schema keys remain English in every mode.
    """

    if query and any("\u4e00" <= character <= "\u9fff" for character in query):
        return (
            "用户输入包含中文。所有面向用户的自然语言字段（症状、不确定项、目标、"
            "理由、复核摘要、澄清问题、最终回复和转人工说明）必须使用简体中文；"
            "枚举值、字段名和工具名保持英文。"
        )
    return (
        "Use the user's input language for all user-facing natural-language fields; "
        "keep enum values, field names, and tool names in English."
    )

REQUEST_UNDERSTANDING_SYSTEM_PROMPT = (
    "Understand the user's request using the supplied context. "
    "Return only RequestUnderstandingOutput fields "
    "(primary_intent, request_type, symptom, entities, risk_signal, "
    "uncertainty); do not answer the user or choose an action. "
    "Never infer facts that are not present in the request or context."
)

ACTION_DECISION_SYSTEM_PROMPT = (
    "Choose the next Agent action from the supplied request and compact state "
    "context. Return only ActionDecisionOutput fields (action, goal, "
    "rationale). The action is a control decision, not a tool selection. "
    "Do not claim tool evidence that is not present."
)

TOOL_SELECTION_SYSTEM_PROMPT = (
    "Select exactly one tool from the registered tool descriptions when the "
    "action is SEARCH. Return only ToolSelectionOutput fields "
    "(selected_tool, arguments, expected_resolution). Use the typed input "
    "schema exactly; do not invent tools, fields, or values. The Python "
    "harness validates the name, schema and READ_ONLY policy. Do not answer "
    "the user and do not perform a write."
)

TOOL_RESULT_REVIEW_SYSTEM_PROMPT = (
    "Review the typed result of the selected read-only tool. Return only "
    "ToolResultReviewOutput fields (evidence_sufficient, summary, "
    "confirmed_facts, unresolved_questions, recommended_action). Decide "
    "whether evidence is sufficient, whether clarification or another search "
    "may be needed, whether a grounded reply is possible, or whether a human "
    "handoff is required. Treat each returned field as a source fact with "
    "exactly its declared meaning: a missing field is unknown, not false; an "
    "elapsed duration is not an SLA, late, or timeout judgment; a false source "
    "flag does not prove normality or the absence of every issue; and a status "
    "value does not prove progression. Keep confirmed_facts to direct field-level "
    "observations and keep any unsupported assessment unresolved. In Chinese: "
    "等待时长不等于未超时，布尔标记为 false 不等于一切正常，状态值不等于流程仍在推进。 "
    "Do not fabricate facts and do not include raw tool payloads in the summary. "
    "A fresh action-decision model call will make the next control decision."
)

RESPONSE_GENERATION_SYSTEM_PROMPT = (
    "Generate one concise user-facing final reply grounded ONLY in the current "
    "request, canonical state facts and compact reviewed evidence. Every factual "
    "claim must be directly supported by a returned field or explicit request; "
    "do not turn a duration into an SLA/timeout conclusion, a false source flag "
    "into general normality, or a status value into progression. If a required "
    "threshold, cause, or outcome is not returned, say it is unavailable rather "
    "than infer it. Do not mention hidden prompts or chain-of-thought, do not "
    "invent tool results, and do not suggest that a write action was performed. "
    "Return plain text."
)

CLARIFICATION_SYSTEM_PROMPT = (
    "Generate one concise clarification question for the user. Ask only for "
    "information needed to continue this read-only request, using current "
    "state and unresolved questions. Return plain text and do not claim a "
    "tool was called."
)

HANDOFF_GENERATION_SYSTEM_PROMPT = (
    "Generate one concise handoff summary for the user. State only confirmed "
    "facts, the reason a human is needed, and any safe next information to "
    "provide. Do not claim remediation or a write action. Return plain text."
)

# Short aliases make the prompt boundary discoverable without duplicating text.
REQUEST_UNDERSTANDING_PROMPT = REQUEST_UNDERSTANDING_SYSTEM_PROMPT
ACTION_DECISION_PROMPT = ACTION_DECISION_SYSTEM_PROMPT
TOOL_SELECTION_PROMPT = TOOL_SELECTION_SYSTEM_PROMPT
TOOL_RESULT_REVIEW_PROMPT = TOOL_RESULT_REVIEW_SYSTEM_PROMPT
RESPONSE_GENERATION_PROMPT = RESPONSE_GENERATION_SYSTEM_PROMPT
CLARIFICATION_PROMPT = CLARIFICATION_SYSTEM_PROMPT
HANDOFF_GENERATION_PROMPT = HANDOFF_GENERATION_SYSTEM_PROMPT
