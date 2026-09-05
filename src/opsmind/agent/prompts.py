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

BOUNDED_ANSWER_POLICY = (
    "Judge sufficiency for a useful bounded answer to the current request, "
    "not completeness about every related unknown. An unresolved item is not "
    "an automatic ASK_USER checklist. Choose ASK_USER only for one specific "
    "missing user-suppliable fact that materially blocks an answer or a useful "
    "registered read-only next action. Choose SEARCH only when a currently "
    "registered capability can resolve a material remaining gap. If the gap is "
    "outside the available capabilities or evidence, state that limitation "
    "instead of promising future investigation. Review recommendations are "
    "advisory; a fresh action decision remains authoritative."
)

TERMINAL_GROUNDING_POLICY = (
    "Use only the current request, compact reviewed evidence, and the available "
    "capability metadata. Preserve request-relevant source identifiers, current "
    "state or ownership, quantities or units, and flags with source-qualified "
    "wording. Unknown causes, thresholds, and outcomes must remain explicit "
    "limits. Never claim an unexecuted call, a result not present in evidence, "
    "a write/remediation, or a capability absent from available_tools. Treat "
    "each returned field as a source fact with exactly its declared meaning: "
    "an elapsed duration is not an SLA, late, or timeout judgment; a false "
    "source flag does not prove universal normality; and a status value does "
    "not prove progression."
)

GROUNDED_RESPONSE_PLAN_SYSTEM_PROMPT = (
    "Create a GroundedResponsePlanOutput for the requested terminal action. "
    "Return only terminal_mode, presentation_intent, evidence_references, "
    "limitation, and clarification_target. Select zero or more relevant "
    "evidence_id/path references from the supplied compact typed evidence. "
    "Use canonical paths such as key_fields.status or "
    "key_fields.waiting_hours; never write a value, factual claim, answer, "
    "summary, rationale, or prose field. The harness rejects unknown IDs, "
    "unknown paths, missing fields, duplicate references, and extra fields, "
    "then renders all factual text deterministically from the source contract. "
    "A limitation is an enum intent only; do not explain it in prose. "
    f"{TERMINAL_GROUNDING_POLICY}"
)

ACTION_DECISION_SYSTEM_PROMPT = (
    "Choose the next Agent action from the supplied request and compact state "
    "context. Return only ActionDecisionOutput fields (action, goal, "
    "rationale). The action is a control decision, not a tool selection. "
    "Do not claim tool evidence that is not present. "
    f"{BOUNDED_ANSWER_POLICY}"
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
    f"{BOUNDED_ANSWER_POLICY}"
)

RESPONSE_GENERATION_SYSTEM_PROMPT = (
    "Select the relevant typed source fields for one concise user-facing final "
    "reply. "
    f"{GROUNDED_RESPONSE_PLAN_SYSTEM_PROMPT}"
)

CLARIFICATION_SYSTEM_PROMPT = (
    "Select a bounded clarification presentation and any already-reviewed typed "
    "source fields. Ask only for one specific missing user-suppliable fact "
    "through clarification_target. "
    f"{GROUNDED_RESPONSE_PLAN_SYSTEM_PROMPT}"
)

HANDOFF_GENERATION_SYSTEM_PROMPT = (
    "Select a bounded handoff presentation and any already-reviewed typed source "
    "fields. The deterministic renderer supplies the handoff wording and never "
    "claims remediation or a write action. "
    f"{GROUNDED_RESPONSE_PLAN_SYSTEM_PROMPT}"
)

# Short aliases make the prompt boundary discoverable without duplicating text.
REQUEST_UNDERSTANDING_PROMPT = REQUEST_UNDERSTANDING_SYSTEM_PROMPT
ACTION_DECISION_PROMPT = ACTION_DECISION_SYSTEM_PROMPT
TOOL_SELECTION_PROMPT = TOOL_SELECTION_SYSTEM_PROMPT
TOOL_RESULT_REVIEW_PROMPT = TOOL_RESULT_REVIEW_SYSTEM_PROMPT
RESPONSE_GENERATION_PROMPT = RESPONSE_GENERATION_SYSTEM_PROMPT
GROUNDED_RESPONSE_PLAN_PROMPT = GROUNDED_RESPONSE_PLAN_SYSTEM_PROMPT
CLARIFICATION_PROMPT = CLARIFICATION_SYSTEM_PROMPT
HANDOFF_GENERATION_PROMPT = HANDOFF_GENERATION_SYSTEM_PROMPT
