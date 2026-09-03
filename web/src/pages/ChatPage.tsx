import { FormEvent, useRef, useState } from "react";
import { sendChat, OpsMindApiError } from "../api/opsmind";
import { ActionBadge, StatusBadge } from "../components/common/Badges";
import { Icon } from "../components/common/Icon";
import { AgentTracePanel } from "../components/chat/AgentTracePanel";
import type { ChatResponse } from "../types/api";

const prompts = [
  "为什么我的工单一直停在审批中？",
  "为什么别人能看到这个菜单，我看不到？",
  "这个工单应该怎么撤回？",
  "为什么页面上的设备数据一直没有更新？",
];

interface Exchange { message: string; response?: ChatResponse; error?: { message: string; requestId?: string } }

export function ChatErrorState({ message, requestId }: { message: string; requestId?: string }) {
  return <div className="error-state" role="alert"><strong>{message}</strong>{requestId && <small>Request ID · {requestId}</small>}</div>;
}

function Understanding({ response }: { response: ChatResponse }) {
  const u = response.understanding;
  const entities = Object.entries(u.entities);
  return (
    <section className="result-block" aria-label="Request Understanding">
      <div className="result-block__heading"><span>01</span><div><h3>Request Understanding</h3><p>请求理解</p></div></div>
      <dl className="data-grid">
        <div><dt>主要意图</dt><dd>{u.primary_intent}</dd></div>
        <div><dt>请求类型</dt><dd>{u.request_type}</dd></div>
        <div><dt>风险信号</dt><dd><StatusBadge tone={u.risk_signal === "NONE" ? "success" : "warning"}>{u.risk_signal}</StatusBadge></dd></div>
        {entities.length > 0 && <div className="data-grid__wide"><dt>识别对象</dt><dd className="entities">{entities.map(([key, value]) => <span key={key}><small>{key}</small>{String(value)}</span>)}</dd></div>}
        {u.symptom && <div className="data-grid__wide"><dt>症状摘要</dt><dd>{u.symptom}</dd></div>}
        {u.uncertainty && <div className="data-grid__wide"><dt>不确定项</dt><dd>{u.uncertainty}</dd></div>}
      </dl>
    </section>
  );
}

function Decision({ response }: { response: ChatResponse }) {
  return (
    <section className="result-block" aria-label="Action Decision">
      <div className="result-block__heading"><span>02</span><div><h3>Action Decision</h3><p>动作决策</p></div></div>
      <div className="decision-line"><span>下一步动作</span><ActionBadge action={response.decision.action} /></div>
      <dl className="decision-copy"><div><dt>目标</dt><dd>{response.decision.goal}</dd></div><div><dt>决策摘要</dt><dd>{response.decision.rationale}</dd></div></dl>
      <p className="phase-note"><Icon name="check" /> 当前运行阶段已完成动作决策。Tool 与最终回复能力尚未接入。</p>
    </section>
  );
}

export function ChatPage() {
  const [input, setInput] = useState("");
  const [exchanges, setExchanges] = useState<Exchange[]>([]);
  const [threadId, setThreadId] = useState<string>();
  const [loading, setLoading] = useState(false);
  const [traceOpen, setTraceOpen] = useState(true);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const latestTrace = exchanges.at(-1)?.response?.trace ?? [];

  async function submit(message: string) {
    const clean = message.trim();
    if (!clean || loading) return;
    setInput("");
    setLoading(true);
    setExchanges((current) => [...current, { message: clean }]);
    try {
      const response = await sendChat({ message: clean, ...(threadId ? { thread_id: threadId } : {}), source_context: { channel: "web-demo" } });
      setThreadId(response.thread_id);
      setExchanges((current) => current.map((item, index) => index === current.length - 1 ? { ...item, response } : item));
      setTraceOpen(true);
    } catch (error) {
      const apiError = error instanceof OpsMindApiError
        ? { message: error.message, requestId: error.requestId }
        : { message: "请求未能完成，请稍后重试。" };
      setExchanges((current) => current.map((item, index) => index === current.length - 1 ? { ...item, error: apiError } : item));
    } finally {
      setLoading(false);
      inputRef.current?.focus();
    }
  }

  function runSubmit(message: string) {
    void submit(message).catch(() => undefined);
  }

  function handleSubmit(event: FormEvent) { event.preventDefault(); runSubmit(input); }

  return (
    <div className={`chat-layout ${traceOpen ? "chat-layout--trace" : ""}`}>
      <section className="chat-main">
        <header className="chat-topbar">
          <div><span className="eyebrow">Phase 1 · Agent Kernel</span><h1>对话调试</h1></div>
          <button className="secondary-button" onClick={() => setTraceOpen((open) => !open)} aria-expanded={traceOpen}><Icon name="panel" />运行详情</button>
        </header>

        <div className="conversation" aria-live="polite">
          {exchanges.length === 0 ? (
            <div className="welcome">
              <span className="welcome__mark"><Icon name="bot" /></span>
              <span className="eyebrow">OpsMind · Online</span>
              <h2>你好，我是 OpsMind</h2>
              <p>我会把你的运维请求拆解为可审计的理解与动作决策。</p>
              <div className="prompt-list">
                {prompts.map((prompt, index) => <button key={prompt} onClick={() => runSubmit(prompt)}><span>0{index + 1}</span>{prompt}<Icon name="arrow" /></button>)}
              </div>
            </div>
          ) : exchanges.map((exchange, index) => (
            <div className="exchange" key={`${exchange.message}-${index}`}>
              <div className="user-message"><span>你</span><p>{exchange.message}</p></div>
              {exchange.response && <div className="agent-response"><div className="agent-response__intro"><span className="mini-mark"><Icon name="bot" /></span><div><strong>已完成请求理解</strong><p>以下内容来自本次真实 Agent Kernel 响应。</p></div></div><Understanding response={exchange.response} /><Decision response={exchange.response} /><small className="request-id">Request ID · {exchange.response.request_id}</small></div>}
              {exchange.error && <ChatErrorState {...exchange.error} />}
            </div>
          ))}
          {loading && <div className="loading-state" role="status"><span /><span /><span />正在理解请求并生成动作决策…</div>}
        </div>

        <form className="composer" onSubmit={handleSubmit}>
          <label htmlFor="chat-input">输入运维问题</label>
          <div className="composer__box"><textarea ref={inputRef} id="chat-input" value={input} onChange={(event) => setInput(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); event.currentTarget.form?.requestSubmit(); } }} rows={2} maxLength={8000} placeholder="描述问题、工单号或可观察到的现象…" disabled={loading} /><button type="submit" disabled={!input.trim() || loading} aria-label="发送消息"><Icon name="send" /></button></div>
          <div className="composer__meta"><span>Enter 发送 · Shift + Enter 换行</span><span>{threadId ? `Session thread · ${threadId.slice(0, 8)}…` : "新会话"}</span></div>
        </form>
      </section>
      {traceOpen && <AgentTracePanel trace={latestTrace} onClose={() => setTraceOpen(false)} />}
    </div>
  );
}
