import { useCallback, useEffect, useRef, useState } from "react";
import { getEval, listEvals, OFFICIAL_EVAL_SUITE_ID, OpsMindApiError, runEval } from "../api/opsmind";
import { StatusBadge } from "../components/common/Badges";
import { PageHeader } from "../components/common/PageHeader";
import type {
  EvalAssertionResult,
  EvalCaseResult,
  EvalCaseStatus,
  EvalJob,
  EvalJobLifecycleStatus,
  EvalJobSummary,
} from "../types/api";

const HISTORY_LIMIT = 20;

function formatTimestamp(value: string): string {
  return new Date(value).toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

function formatDuration(durationMs: number | null): string {
  if (durationMs === null) return "N/A";
  return durationMs < 1_000 ? `${Math.round(durationMs)} ms` : `${(durationMs / 1_000).toFixed(2)} s`;
}

function statusTone(status: EvalCaseStatus | "PASS" | "FAIL" | "ERROR"): "success" | "warning" | "danger" {
  if (status === "PASS") return "success";
  if (status === "FAIL") return "warning";
  return "danger";
}

function lifecycleTone(status: EvalJobLifecycleStatus): "success" | "warning" | "danger" | "neutral" {
  if (status === "COMPLETED") return "success";
  if (status === "FAILED") return "danger";
  return "neutral";
}

function safeValueText(value: EvalAssertionResult["expected_safe"]): string {
  if (value === null) return "null";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  try {
    const serialized = JSON.stringify(value);
    if (serialized.length <= 1_000) return serialized;
    return `${serialized.slice(0, 997)}…`;
  } catch {
    return "[unavailable]";
  }
}

function getUiError(error: unknown): { message: string; requestId?: string } {
  if (error instanceof OpsMindApiError) return { message: error.message, requestId: error.requestId };
  return { message: "请求未能完成，请稍后重试。" };
}

function QualitySummary({ job }: { job: EvalJob | EvalJobSummary }) {
  if (job.lifecycle_status !== "COMPLETED") {
    return <span className="eval-quality--unavailable">未完成，不计算质量指标</span>;
  }
  return <span className="eval-quality-summary"><strong>PASS {job.passed_count}</strong><strong>FAIL {job.failed_count}</strong><strong>ERROR {job.error_count}</strong></span>;
}

function Metrics({ job }: { job: EvalJob }) {
  const completed = job.lifecycle_status === "COMPLETED";
  const passRate = completed && job.case_count > 0 ? `${((job.passed_count / job.case_count) * 100).toFixed(1)}%` : "N/A";
  const metrics = [
    ["Cases", completed ? job.case_count : "N/A"],
    ["Passed", completed ? job.passed_count : "N/A"],
    ["Failed", completed ? job.failed_count : "N/A"],
    ["Errors", completed ? job.error_count : "N/A"],
    ["Pass Rate", passRate],
  ];
  return <div className="metric-strip evaluation-metrics">{metrics.map(([label, value]) => <div key={label}><span>{label}</span><strong>{value}</strong></div>)}</div>;
}

function JobMetadata({ job }: { job: EvalJob }) {
  return (
    <section className="eval-card eval-metadata" aria-label="评测任务元数据">
      <div className="eval-card__heading"><div><span className="eyebrow">Selected Job</span><h2>评测任务信息</h2></div><StatusBadge tone={lifecycleTone(job.lifecycle_status)}>{job.lifecycle_status}</StatusBadge></div>
      <dl>
        <div><dt>Suite</dt><dd>{job.suite_id}</dd></div>
        <div><dt>Version</dt><dd>{job.suite_version}</dd></div>
        <div><dt>Runtime</dt><dd className="eval-runtime">{job.runtime_identity}</dd></div>
        <div><dt>Started At</dt><dd>{formatTimestamp(job.started_at)}</dd></div>
        <div><dt>Duration</dt><dd>{formatDuration(job.duration_ms)}</dd></div>
        {job.build_sha && <div><dt>Build SHA</dt><dd className="eval-id">{job.build_sha}</dd></div>}
        <div className="eval-metadata__wide"><dt>Job ID</dt><dd className="eval-id">{job.eval_job_id}</dd></div>
      </dl>
    </section>
  );
}

function ErrorNotice({ message, requestId, onRetry, retryLabel }: { message: string; requestId?: string; onRetry?: () => void; retryLabel?: string }) {
  return <div className="error-state eval-error" role="alert"><div><strong>{message}</strong>{requestId && <small>Request ID · {requestId}</small>}</div>{onRetry && <button type="button" onClick={onRetry}>{retryLabel ?? "重试"}</button>}</div>;
}

function HistoryItem({ item, selected, onSelect }: { item: EvalJobSummary; selected: boolean; onSelect: () => void }) {
  return (
    <button type="button" className={`eval-history-item ${selected ? "eval-history-item--selected" : ""}`} aria-pressed={selected} onClick={onSelect}>
      <span className="eval-history-item__top"><strong>{item.suite_id}</strong><small>{formatTimestamp(item.started_at)}</small></span>
      <span className="eval-history-item__meta">v{item.suite_version} · {item.runtime_identity}</span>
      <span className="eval-history-item__bottom"><QualitySummary job={item} /><small>{formatDuration(item.duration_ms)}</small></span>
    </button>
  );
}

function CaseRow({ item, selected, onSelect }: { item: EvalCaseResult; selected: boolean; onSelect: () => void }) {
  const passedAssertions = item.assertions.filter((assertion) => assertion.status === "PASS").length;
  return (
    <button type="button" className={`eval-case-row ${selected ? "eval-case-row--selected" : ""}`} aria-expanded={selected} onClick={onSelect}>
      <span className="eval-case-row__identity"><small>{item.case_id}</small><strong>{item.title}</strong>{item.known_gap && <span className="known-gap-badge">Known Gap</span>}</span>
      <StatusBadge tone={statusTone(item.status)}>{item.status}</StatusBadge>
      <span className="eval-case-row__stat"><small>Assertions</small><strong>{passedAssertions} / {item.assertions.length}</strong></span>
      <span className="eval-case-row__stat"><small>Runs</small><strong>{item.run_ids.length}</strong></span>
    </button>
  );
}

function CaseDetail({ item }: { item: EvalCaseResult }) {
  return (
    <section className="eval-case-detail" aria-label={`${item.case_id} 评测详情`}>
      <div className="eval-case-detail__heading"><div><span className="eyebrow">Case Detail · {item.case_id}</span><h3>{item.title}</h3></div><StatusBadge tone={statusTone(item.status)}>{item.status}</StatusBadge></div>
      <dl className="eval-case-detail__meta">
        <div><dt>Status</dt><dd>{item.status}</dd></div>
        <div><dt>Started At</dt><dd>{formatTimestamp(item.started_at)}</dd></div>
        <div><dt>Duration</dt><dd>{formatDuration(item.duration_ms)}</dd></div>
        {item.error_code && <div><dt>Error Code</dt><dd className="eval-id">{item.error_code}</dd></div>}
      </dl>
      {item.known_gap && <div className="known-gap-note"><StatusBadge tone="warning">Known Gap</StatusBadge><span>{item.known_gap}</span></div>}
      <div className="eval-detail-section"><h4>关联运行记录</h4>{item.run_ids.length > 0 ? <ol className="eval-run-list">{item.run_ids.map((runId, index) => <li key={`${runId}-${index}`}><span>Turn {index + 1}</span><code>{runId}</code></li>)}</ol> : <p className="eval-muted">本 Case 没有可展示的运行记录。</p>}</div>
      <div className="eval-detail-section"><h4>Assertions</h4>{item.assertions.length > 0 ? <div className="eval-assertions">{item.assertions.map((assertion) => <AssertionDetail key={assertion.assertion_id} assertion={assertion} />)}</div> : <p className="eval-muted">此 Case 未返回断言结果。</p>}</div>
    </section>
  );
}

function AssertionDetail({ assertion }: { assertion: EvalAssertionResult }) {
  return (
    <article className="eval-assertion">
      <div className="eval-assertion__heading"><div><strong>{assertion.assertion_id}</strong><small>{assertion.type}</small></div><div className="eval-assertion__badges"><StatusBadge tone={statusTone(assertion.status)}>{assertion.status}</StatusBadge>{assertion.blocking && <StatusBadge tone="neutral">Blocking</StatusBadge>}</div></div>
      <p>{assertion.message}</p>
      <dl><div><dt>Expected</dt><dd><code>{safeValueText(assertion.expected_safe)}</code></dd></div><div><dt>Actual</dt><dd><code>{safeValueText(assertion.actual_safe)}</code></dd></div></dl>
    </article>
  );
}

function JobDetail({ job, selectedCaseId, onSelectCase }: { job: EvalJob; selectedCaseId: string | null; onSelectCase: (caseId: string) => void }) {
  const selectedCase = job.case_results.find((item) => item.case_id === selectedCaseId);
  return (
    <>
      <Metrics job={job} />
      <JobMetadata job={job} />
      {job.lifecycle_status === "FAILED" && <div className="eval-job-failure" role="status"><strong>评测任务失败</strong><span>基础设施未能完成本次运行，不能将其当作 Case FAIL。</span>{job.error_code && <code>{job.error_code}</code>}</div>}
      {job.lifecycle_status === "STARTED" && <div className="eval-job-running" role="status"><strong>评测运行中 / 未完成</strong><span>后端尚未返回最终 Case 结果，当前不计算 Pass Rate。</span></div>}
      {job.lifecycle_status === "COMPLETED" && <section className="eval-card eval-cases" aria-label="评测 Case 列表"><div className="eval-card__heading"><div><span className="eyebrow">Case Results</span><h2>Case 结果</h2></div><QualitySummary job={job} /></div><div className="eval-case-list">{job.case_results.map((item) => <CaseRow key={item.case_id} item={item} selected={item.case_id === selectedCaseId} onSelect={() => onSelectCase(item.case_id)} />)}</div>{selectedCase && <CaseDetail item={selectedCase} />}</section>}
    </>
  );
}

export function EvaluationPage() {
  const [history, setHistory] = useState<EvalJobSummary[]>([]);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [historyError, setHistoryError] = useState<{ message: string; requestId?: string } | null>(null);
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const [selectedJob, setSelectedJob] = useState<EvalJob | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<{ message: string; requestId?: string } | null>(null);
  const [selectedCaseId, setSelectedCaseId] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<{ message: string; requestId?: string } | null>(null);
  const detailRequestRef = useRef(0);
  const selectedJobIdRef = useRef<string | null>(null);
  const historyAbortRef = useRef<AbortController | null>(null);
  const detailAbortRef = useRef<AbortController | null>(null);
  const runAbortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    selectedJobIdRef.current = selectedJobId;
  }, [selectedJobId]);

  const loadDetail = useCallback((evalJobId: string) => {
    detailAbortRef.current?.abort();
    const controller = new AbortController();
    detailAbortRef.current = controller;
    const requestId = detailRequestRef.current + 1;
    detailRequestRef.current = requestId;
    selectedJobIdRef.current = evalJobId;
    setSelectedJobId(evalJobId);
    setSelectedJob(null);
    setSelectedCaseId(null);
    setDetailLoading(true);
    setDetailError(null);
    void getEval(evalJobId, controller.signal).then((job) => {
      if (requestId !== detailRequestRef.current) return;
      setSelectedJob(job);
    }).catch((error: unknown) => {
      if (controller.signal.aborted || requestId !== detailRequestRef.current) return;
      setDetailError(getUiError(error));
    }).finally(() => {
      if (requestId === detailRequestRef.current) setDetailLoading(false);
    });
  }, []);

  const loadHistory = useCallback(async (selectNewest = false) => {
    historyAbortRef.current?.abort();
    const controller = new AbortController();
    historyAbortRef.current = controller;
    setHistoryLoading(true);
    setHistoryError(null);
    try {
      const summaries = await listEvals(HISTORY_LIMIT, controller.signal);
      if (controller.signal.aborted) return;
      setHistory(summaries);
      const currentId = selectedJobIdRef.current;
      const shouldSelect = selectNewest || currentId === null || !summaries.some((item) => item.eval_job_id === currentId);
      if (summaries.length === 0 && shouldSelect) {
        detailAbortRef.current?.abort();
        detailRequestRef.current += 1;
        selectedJobIdRef.current = null;
        setSelectedJobId(null);
        setSelectedJob(null);
        setSelectedCaseId(null);
        setDetailError(null);
      } else if (summaries.length > 0 && shouldSelect) {
        loadDetail(summaries[0].eval_job_id);
      }
    } catch (error: unknown) {
      if (!controller.signal.aborted) setHistoryError(getUiError(error));
    } finally {
      if (!controller.signal.aborted) setHistoryLoading(false);
    }
  }, [loadDetail]);

  useEffect(() => {
    const initialLoad = window.setTimeout(() => { void loadHistory(true); }, 0);
    return () => {
      window.clearTimeout(initialLoad);
      historyAbortRef.current?.abort();
      detailAbortRef.current?.abort();
      runAbortRef.current?.abort();
    };
  }, [loadHistory]);

  async function handleRun() {
    if (running) return;
    runAbortRef.current?.abort();
    const controller = new AbortController();
    runAbortRef.current = controller;
    setRunning(true);
    setRunError(null);
    try {
      const job = await runEval({ suite_id: OFFICIAL_EVAL_SUITE_ID }, controller.signal);
      if (controller.signal.aborted) return;
      selectedJobIdRef.current = job.eval_job_id;
      setSelectedJobId(job.eval_job_id);
      setSelectedJob(job);
      setSelectedCaseId(null);
      setDetailError(null);
      await loadHistory(false);
    } catch (error: unknown) {
      if (!controller.signal.aborted) setRunError(getUiError(error));
    } finally {
      if (!controller.signal.aborted) setRunning(false);
    }
  }

  const empty = !historyLoading && !historyError && history.length === 0;
  return (
    <div className="page page-enter evaluation-page">
      <PageHeader eyebrow="Golden Suite · Real Runtime" title="运行与评测" description="运行官方 Golden Suite，并查看真实 Agent 评测结果与历史记录。" action={<div className="header-actions"><button type="button" className="secondary-button" onClick={() => void loadHistory(false)} disabled={historyLoading}>刷新记录</button><button type="button" className="primary-button" onClick={() => void handleRun()} disabled={running}>{running ? "评测运行中…" : "运行 Golden Suite"}</button></div>} />
      {runError && <ErrorNotice {...runError} onRetry={() => void handleRun()} retryLabel="重试本次运行" />}
      <div className="evaluation-layout">
        <aside className="eval-history-panel" aria-label="评测历史记录"><div className="eval-history-panel__heading"><div><span className="eyebrow">History · {HISTORY_LIMIT}</span><h2>历史评测</h2></div>{history.length > 0 && <span>{history.length} 条</span>}</div>{historyError && <ErrorNotice {...historyError} onRetry={() => void loadHistory(false)} retryLabel="重试加载" />}{historyLoading && history.length === 0 && <p className="eval-muted">正在加载评测记录…</p>}{empty && <div className="eval-empty"><strong>还没有评测记录</strong><span>运行一次 Golden Suite 后，这里会显示 Case 结果、断言和关联运行记录。</span></div>}{history.length > 0 && <div className="eval-history-list">{history.map((item) => <HistoryItem key={item.eval_job_id} item={item} selected={item.eval_job_id === selectedJobId} onSelect={() => loadDetail(item.eval_job_id)} />)}</div>}</aside>
        <main className="eval-detail-panel" aria-live="polite">{detailLoading && <p className="eval-loading" role="status">正在加载评测详情…</p>}{detailError && !detailLoading && <ErrorNotice {...detailError} onRetry={() => selectedJobId && loadDetail(selectedJobId)} retryLabel="重试加载详情" />}{selectedJob && !detailLoading && !detailError && <JobDetail job={selectedJob} selectedCaseId={selectedCaseId} onSelectCase={(caseId) => setSelectedCaseId((current) => current === caseId ? null : caseId)} />}{!selectedJob && !detailLoading && !detailError && !empty && !historyError && <p className="eval-muted">请选择一条评测记录查看详情。</p>}</main>
      </div>
    </div>
  );
}
