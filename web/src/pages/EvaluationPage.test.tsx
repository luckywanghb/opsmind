import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { EvalJob, EvalJobSummary } from "../types/api";
import { getEval, listEvals, OpsMindApiError, runEval } from "../api/opsmind";
import { EvaluationPage } from "./EvaluationPage";

vi.mock("../api/opsmind", async () => {
  const actual = await vi.importActual<typeof import("../api/opsmind")>("../api/opsmind");
  return { ...actual, getEval: vi.fn(), listEvals: vi.fn(), runEval: vi.fn() };
});

const mockedGetEval = vi.mocked(getEval);
const mockedListEvals = vi.mocked(listEvals);
const mockedRunEval = vi.mocked(runEval);

const timestamp = "2026-09-06T00:00:00Z";
const assertion = {
  assertion_id: "required-tool",
  type: "required_tool_used",
  blocking: true,
  status: "PASS" as const,
  expected_safe: "work_order_query",
  actual_safe: "work_order_query",
  message: "Required tool was used.",
};

const completedJob: EvalJob = {
  eval_job_id: "eval-42",
  suite_id: "opsmind-golden",
  suite_version: "0.1",
  lifecycle_status: "COMPLETED",
  case_count: 3,
  passed_count: 1,
  failed_count: 1,
  error_count: 1,
  started_at: timestamp,
  completed_at: "2026-09-06T00:00:02Z",
  duration_ms: 2_000,
  app_version: "0.1.0",
  build_sha: "build-42",
  runtime_identity: "mock",
  error_code: null,
  case_results: [
    {
      eval_job_id: "eval-42",
      case_id: "C05",
      title: "Normal Work-order Wait",
      status: "PASS",
      known_gap: null,
      run_ids: ["run-pass"],
      assertions: [assertion, { ...assertion, assertion_id: "evidence", expected_safe: { status: "APPROVING" }, actual_safe: { status: "APPROVING" } }],
      started_at: timestamp,
      completed_at: timestamp,
      duration_ms: 500,
      error_code: null,
    },
    {
      eval_job_id: "eval-42",
      case_id: "C09",
      title: "HTTP 500 while opening system",
      status: "FAIL",
      known_gap: "LOG_SEARCH_NOT_IMPLEMENTED",
      run_ids: ["run-fail"],
      assertions: [{ ...assertion, assertion_id: "log-search", status: "FAIL", expected_safe: "log_search", actual_safe: "incident_query", message: "Expected log search capability is not registered." }],
      started_at: timestamp,
      completed_at: timestamp,
      duration_ms: 600,
      error_code: null,
    },
    {
      eval_job_id: "eval-42",
      case_id: "C12",
      title: "Continue unresolved case",
      status: "ERROR",
      known_gap: "CONVERSATION_PERSISTENCE_NOT_IMPLEMENTED",
      run_ids: ["run-turn-1", "run-turn-2"],
      assertions: [],
      started_at: timestamp,
      completed_at: timestamp,
      duration_ms: 900,
      error_code: "EVAL_ASSERTION_ERROR",
    },
  ],
  case_runs: [
    { eval_job_id: "eval-42", case_id: "C05", turn_index: 0, run_id: "run-pass" },
    { eval_job_id: "eval-42", case_id: "C09", turn_index: 0, run_id: "run-fail" },
    { eval_job_id: "eval-42", case_id: "C12", turn_index: 0, run_id: "run-turn-1" },
    { eval_job_id: "eval-42", case_id: "C12", turn_index: 1, run_id: "run-turn-2" },
  ],
};

const summaryFromJob = (job: EvalJob): EvalJobSummary => ({
  eval_job_id: job.eval_job_id,
  suite_id: job.suite_id,
  suite_version: job.suite_version,
  lifecycle_status: job.lifecycle_status,
  case_count: job.case_count,
  passed_count: job.passed_count,
  failed_count: job.failed_count,
  error_count: job.error_count,
  started_at: job.started_at,
  completed_at: job.completed_at,
  duration_ms: job.duration_ms,
  app_version: job.app_version,
  build_sha: job.build_sha,
  runtime_identity: job.runtime_identity,
  error_code: job.error_code,
});

function failedJob(): EvalJob {
  return {
    ...summaryFromJob(completedJob),
    eval_job_id: "eval-failed",
    lifecycle_status: "FAILED",
    case_count: 3,
    passed_count: 0,
    failed_count: 0,
    error_count: 0,
    completed_at: "2026-09-06T00:00:02Z",
    duration_ms: 2_000,
    error_code: "EVAL_RUN_FAILED",
    case_results: [],
    case_runs: [],
  };
}

function startedJob(): EvalJob {
  return {
    ...summaryFromJob(completedJob),
    eval_job_id: "eval-started",
    lifecycle_status: "STARTED",
    case_count: 3,
    passed_count: 0,
    failed_count: 0,
    error_count: 0,
    completed_at: null,
    duration_ms: null,
    error_code: null,
    case_results: [],
    case_runs: [],
  };
}

beforeEach(() => {
  mockedGetEval.mockReset();
  mockedListEvals.mockReset();
  mockedRunEval.mockReset();
});

describe("EvaluationPage", () => {
  it("shows a truthful empty state without fake metrics", async () => {
    mockedListEvals.mockResolvedValue([]);
    render(<EvaluationPage />);
    expect(await screen.findByText("还没有评测记录")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "运行 Golden Suite" })).toBeEnabled();
    expect(screen.queryByText("87.5%")).not.toBeInTheDocument();
    expect(screen.queryByText("设计演示数据，不代表生产遥测")).not.toBeInTheDocument();
    expect(mockedGetEval).not.toHaveBeenCalled();
  });

  it("loads the newest history detail and renders real metadata and metrics", async () => {
    const summary = summaryFromJob(completedJob);
    mockedListEvals.mockResolvedValue([summary]);
    mockedGetEval.mockResolvedValue(completedJob);
    render(<EvaluationPage />);
    expect(await screen.findByText("评测任务信息")).toBeInTheDocument();
    expect(screen.getByText("mock")).toBeInTheDocument();
    expect(screen.getByText("build-42")).toBeInTheDocument();
    expect(screen.getByText("33.3%")).toBeInTheDocument();
    expect(screen.getAllByText("PASS 1").length).toBeGreaterThan(0);
    expect(screen.getAllByText("FAIL 1").length).toBeGreaterThan(0);
    expect(screen.getAllByText("ERROR 1").length).toBeGreaterThan(0);
    expect(mockedListEvals).toHaveBeenCalledWith(20, expect.any(AbortSignal));
    expect(mockedGetEval).toHaveBeenCalledWith("eval-42", expect.any(AbortSignal));
  });

  it("runs exactly once, disables the button, displays the response, and refreshes history", async () => {
    mockedListEvals.mockResolvedValueOnce([]).mockResolvedValueOnce([summaryFromJob(completedJob)]);
    let resolveRun!: (job: EvalJob) => void;
    mockedRunEval.mockReturnValue(new Promise((resolve) => { resolveRun = resolve; }));
    mockedGetEval.mockResolvedValue(completedJob);
    render(<EvaluationPage />);
    await screen.findByText("还没有评测记录");
    const button = screen.getByRole("button", { name: "运行 Golden Suite" });
    fireEvent.click(button);
    fireEvent.click(button);
    expect(mockedRunEval).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "评测运行中…" })).toBeDisabled();
    resolveRun(completedJob);
    expect(await screen.findByText("评测任务信息")).toBeInTheDocument();
    await waitFor(() => expect(mockedListEvals).toHaveBeenCalledTimes(2));
    expect(mockedRunEval).toHaveBeenCalledWith({ suite_id: "opsmind-golden" }, expect.any(AbortSignal));
    expect(mockedGetEval).not.toHaveBeenCalled();
  });

  it("keeps previous data visible when a new run fails", async () => {
    mockedListEvals.mockResolvedValue([summaryFromJob(completedJob)]);
    mockedGetEval.mockResolvedValue(completedJob);
    mockedRunEval.mockRejectedValue(new OpsMindApiError("EVAL_RUN_FAILED", "本次运行失败，请稍后重试。", "req-run", 500));
    render(<EvaluationPage />);
    await screen.findByText("评测任务信息");
    fireEvent.click(screen.getByRole("button", { name: "运行 Golden Suite" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("本次运行失败");
    expect(screen.getByText("mock")).toBeInTheDocument();
    expect(screen.getByText("eval-42")).toBeInTheDocument();
  });

  it("distinguishes PASS, FAIL, ERROR, known gaps, assertions, and ordered run IDs", async () => {
    mockedListEvals.mockResolvedValue([summaryFromJob(completedJob)]);
    mockedGetEval.mockResolvedValue(completedJob);
    render(<EvaluationPage />);
    await screen.findByText("C05");
    expect(screen.getByText("C09")).toBeInTheDocument();
    expect(screen.getByText("C12")).toBeInTheDocument();
    expect(screen.getAllByText("Known Gap").length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: /C12.*Continue unresolved case/ }));
    expect(await screen.findByText("Turn 1")).toBeInTheDocument();
    expect(screen.getByText("Turn 2")).toBeInTheDocument();
    expect(screen.getByText("run-turn-1")).toBeInTheDocument();
    expect(screen.getByText("run-turn-2")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /C05.*Normal Work-order Wait/ }));
    expect(screen.getAllByText("required_tool_used").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Blocking").length).toBeGreaterThan(0);
    expect(screen.getAllByText("work_order_query").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Required tool was used.").length).toBeGreaterThan(0);
  });

  it("does not fabricate metrics for FAILED or STARTED jobs", async () => {
    const failed = failedJob();
    mockedListEvals.mockResolvedValue([summaryFromJob(failed)]);
    mockedGetEval.mockResolvedValue(failed);
    render(<EvaluationPage />);
    expect(await screen.findByText("评测任务失败")).toBeInTheDocument();
    expect(screen.getAllByText("N/A").length).toBeGreaterThanOrEqual(5);
    expect(screen.queryByText("Case 结果")).not.toBeInTheDocument();

    mockedListEvals.mockReset();
    mockedGetEval.mockReset();
    mockedListEvals.mockResolvedValue([summaryFromJob(startedJob())]);
    mockedGetEval.mockResolvedValue(startedJob());
    render(<EvaluationPage />);
    expect(await screen.findByText("评测运行中 / 未完成")).toBeInTheDocument();
    expect(screen.queryByText("Case 结果")).not.toBeInTheDocument();
  });

  it("prevents stale detail responses from overwriting a newer history selection", async () => {
    const jobA = { ...completedJob, eval_job_id: "eval-a", runtime_identity: "runtime-a" };
    const jobB = { ...completedJob, eval_job_id: "eval-b", runtime_identity: "runtime-b" };
    const summaryA = summaryFromJob(jobA);
    const summaryB = summaryFromJob(jobB);
    let resolveA!: (job: EvalJob) => void;
    let resolveB!: (job: EvalJob) => void;
    mockedListEvals.mockResolvedValue([summaryA, summaryB]);
    mockedGetEval.mockReturnValueOnce(new Promise((resolve) => { resolveA = resolve; })).mockReturnValueOnce(new Promise((resolve) => { resolveB = resolve; }));
    render(<EvaluationPage />);
    await waitFor(() => expect(screen.getAllByRole("button", { name: /runtime-a/ }).length).toBe(1));
    fireEvent.click(screen.getByRole("button", { name: /runtime-b/ }));
    resolveB(jobB);
    expect(await screen.findByText("runtime-b")).toBeInTheDocument();
    resolveA(jobA);
    await waitFor(() => expect(screen.getByLabelText("评测任务元数据")).toHaveTextContent("runtime-b"));
    expect(screen.getByLabelText("评测任务元数据")).not.toHaveTextContent("runtime-a");
  });

  it("renders untrusted result text as text, not executable markup", async () => {
    const unsafeJob: EvalJob = { ...completedJob, runtime_identity: "<img src=x onerror=alert(1)>", case_results: [{ ...completedJob.case_results[0], known_gap: "<script>alert(1)</script>", assertions: [{ ...assertion, message: "<b>unsafe</b>" }] }] };
    mockedListEvals.mockResolvedValue([summaryFromJob(unsafeJob)]);
    mockedGetEval.mockResolvedValue(unsafeJob);
    render(<EvaluationPage />);
    expect(await screen.findByText("<img src=x onerror=alert(1)>")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /C05.*Normal Work-order Wait/ }));
    expect(await screen.findByText("<b>unsafe</b>")).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });
});
