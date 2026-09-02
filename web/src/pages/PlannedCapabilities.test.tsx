import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, it } from "vitest";
import { EvaluationPage } from "./EvaluationPage";

it("keeps evaluation execution visibly planned and disabled", () => {
  render(<MemoryRouter><EvaluationPage /></MemoryRouter>);
  const button = screen.getByRole("button", { name: "运行评测 · Planned" });
  expect(button).toBeDisabled();
  expect(screen.getByText("设计演示数据，不代表生产遥测")).toBeInTheDocument();
});
