import type { components } from "@banking/api-client";

type Conversation = components["schemas"]["Conversation"];
type ConversationCreate = components["schemas"]["ConversationCreate"];
type ConversationDetail = components["schemas"]["ConversationDetail"];
type MessageAccepted = components["schemas"]["MessageAccepted"];
type Task = components["schemas"]["Task"];
type ReportListItem = components["schemas"]["ReportListItem"];
type ReportResponse = components["schemas"]["ReportResponse"];

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
    const detail = payload?.detail ?? "请求失败";
    throw new Error(`请求失败（${response.status}）：${detail}`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  listConversations: () => request<Conversation[]>("/api/v1/conversations"),
  createConversation: (body: ConversationCreate) =>
    request<Conversation>("/api/v1/conversations", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  getConversation: (conversationId: string) =>
    request<ConversationDetail>(`/api/v1/conversations/${conversationId}`),
  postMessage: (conversationId: string, content: string) =>
    request<MessageAccepted>(`/api/v1/conversations/${conversationId}/messages`, {
      method: "POST",
      body: JSON.stringify({ content }),
    }),
  listTasks: (conversationId: string) =>
    request<Task[]>(`/api/v1/tasks?conversation_id=${encodeURIComponent(conversationId)}`),
  getTask: (taskId: string) => request<Task>(`/api/v1/tasks/${taskId}`),
  listReports: (conversationId?: string, limit = 20, offset = 0) => {
    const query = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    if (conversationId) query.set("conversation_id", conversationId);
    return request<ReportListItem[]>(`/api/v1/reports?${query.toString()}`);
  },
  getReport: (reportId: string) =>
    request<ReportResponse>(`/api/v1/reports/${encodeURIComponent(reportId)}`),
};
