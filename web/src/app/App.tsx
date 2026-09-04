import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "../components/layout/AppShell";
import { AgentConfigPage } from "../pages/AgentConfigPage";
import { ChatPage } from "../pages/ChatPage";
import { EvaluationPage } from "../pages/EvaluationPage";
import { KnowledgePage } from "../pages/KnowledgePage";
import { SopDetailPage } from "../pages/SopDetailPage";

export function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route path="/chat" element={<ChatPage />} />
        <Route path="/agent" element={<AgentConfigPage />} />
        <Route path="/knowledge" element={<KnowledgePage />} />
        <Route path="/knowledge/:id" element={<SopDetailPage />} />
        <Route path="/evaluation" element={<EvaluationPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/chat" replace />} />
    </Routes>
  );
}
