import type { components } from "@banking/api-client";

type Conversation = components["schemas"]["Conversation"];
type ConversationCreate = components["schemas"]["ConversationCreate"];
type ConversationDetail = components["schemas"]["ConversationDetail"];
type MessageAccepted = components["schemas"]["MessageAccepted"];
type Task = components["schemas"]["Task"];
type ReportListItem = components["schemas"]["ReportListItem"];
type ReportResponse = components["schemas"]["ReportResponse"];
type Workflow = components["schemas"]["Workflow"];
type OperationResource = components["schemas"]["OperationResource"];
type SubscriptionAnalysisSnapshot = components["schemas"]["SubscriptionAnalysisSnapshot"];
type SubscriptionItem = components["schemas"]["SubscriptionItem"];

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

let accessTokenProvider: () => Promise<string | null> = async () => null;

export function setAccessTokenProvider(provider: () => Promise<string | null>) {
  accessTokenProvider = provider;
}

export async function getAuthorizationHeaders(): Promise<Record<string, string>> {
  const token = await accessTokenProvider();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const authorization = await getAuthorizationHeaders();
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...authorization, ...init?.headers },
  });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as {
      detail?: string | { code?: string; message?: string };
    } | null;
    const rawDetail = payload?.detail;
    const detail =
      typeof rawDetail === "string"
        ? rawDetail
        : rawDetail?.code ?? rawDetail?.message ?? "请求失败";
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
  listWorkflows: (conversationId: string) =>
    request<Workflow[]>(
      `/api/v1/workflows?conversation_id=${encodeURIComponent(conversationId)}`,
    ),
  getWorkflow: (workflowId: string) =>
    request<Workflow>(`/api/v1/workflows/${encodeURIComponent(workflowId)}`),
  selectPayee: (workflowId: string, payeeId: string, expectedVersion: number) =>
    request<Workflow>(`/api/v1/workflows/${encodeURIComponent(workflowId)}/actions/select-payee`, {
      method: "POST",
      body: JSON.stringify({ payee_id: payeeId, expected_version: expectedVersion }),
    }),
  selectSourceAccount: (workflowId: string, accountId: string, expectedVersion: number) =>
    request<Workflow>(
      `/api/v1/workflows/${encodeURIComponent(workflowId)}/actions/select-source-account`,
      {
        method: "POST",
        body: JSON.stringify({ account_id: accountId, expected_version: expectedVersion }),
      },
    ),
  setTransferAmount: (workflowId: string, amount: string, expectedVersion: number) =>
    request<Workflow>(`/api/v1/workflows/${encodeURIComponent(workflowId)}/actions/set-amount`, {
      method: "POST",
      body: JSON.stringify({ amount, expected_version: expectedVersion }),
    }),
  setRecipientQuery: (
    workflowId: string,
    recipientQuery: string,
    expectedVersion: number,
  ) =>
    request<Workflow>(
      `/api/v1/workflows/${encodeURIComponent(workflowId)}/actions/set-recipient-query`,
      {
        method: "POST",
        body: JSON.stringify({
          recipient_query: recipientQuery,
          expected_version: expectedVersion,
        }),
      },
    ),
  approveTransfer: (workflowId: string, expectedVersion: number) =>
    request<Workflow>(`/api/v1/workflows/${encodeURIComponent(workflowId)}/actions/approve`, {
      method: "POST",
      body: JSON.stringify({ expected_version: expectedVersion }),
    }),
  startTransferReauthentication: (workflowId: string, expectedVersion: number) =>
    request<Workflow>(
      `/api/v1/workflows/${encodeURIComponent(workflowId)}/actions/start-reauth`,
      {
        method: "POST",
        body: JSON.stringify({ expected_version: expectedVersion }),
      },
    ),
  verifyTransferReauthentication: (
    workflowId: string,
    reauthId: string,
    verificationCode: string,
    expectedVersion: number,
  ) =>
    request<Workflow>(
      `/api/v1/workflows/${encodeURIComponent(workflowId)}/actions/verify-reauth`,
      {
        method: "POST",
        body: JSON.stringify({
          reauth_id: reauthId,
          verification_code: verificationCode,
          expected_version: expectedVersion,
        }),
      },
    ),
  commitTransfer: (workflowId: string, expectedVersion: number) =>
    request<Workflow>(`/api/v1/workflows/${encodeURIComponent(workflowId)}/actions/commit`, {
      method: "POST",
      body: JSON.stringify({ expected_version: expectedVersion }),
    }),
  getOperation: (operationId: string) =>
    request<OperationResource>(`/api/v1/operations/${encodeURIComponent(operationId)}`),
  reconcileOperation: (operationId: string, expectedVersion: number) =>
    request<OperationResource>(
      `/api/v1/operations/${encodeURIComponent(operationId)}/actions/reconcile`,
      {
        method: "POST",
        body: JSON.stringify({ expected_version: expectedVersion }),
      },
    ),
  cancelWorkflow: (workflowId: string, expectedVersion: number) =>
    request<Workflow>(`/api/v1/workflows/${encodeURIComponent(workflowId)}/actions/cancel`, {
      method: "POST",
      body: JSON.stringify({ expected_version: expectedVersion }),
    }),
  listReports: (conversationId?: string, limit = 20, offset = 0) => {
    const query = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    if (conversationId) query.set("conversation_id", conversationId);
    return request<ReportListItem[]>(`/api/v1/reports?${query.toString()}`);
  },
  getReport: (reportId: string) =>
    request<ReportResponse>(`/api/v1/reports/${encodeURIComponent(reportId)}`),
  listSubscriptions: (upcomingDays = 7) =>
    request<SubscriptionAnalysisSnapshot>(
      `/api/v1/subscriptions?upcoming_days=${encodeURIComponent(String(upcomingDays))}`,
    ),
  getSubscription: (subscriptionId: string) =>
    request<SubscriptionItem>(
      `/api/v1/subscriptions/${encodeURIComponent(subscriptionId)}`,
    ),
  selectSubscription: (
    workflowId: string,
    subscriptionId: string,
    expectedVersion: number,
  ) =>
    request<Workflow>(
      `/api/v1/workflows/${encodeURIComponent(workflowId)}/actions/select-subscription`,
      {
        method: "POST",
        body: JSON.stringify({
          subscription_id: subscriptionId,
          expected_version: expectedVersion,
        }),
      },
    ),
  approveWorkflow: (workflowId: string, expectedVersion: number) =>
    request<Workflow>(`/api/v1/workflows/${encodeURIComponent(workflowId)}/actions/approve`, {
      method: "POST",
      body: JSON.stringify({ expected_version: expectedVersion }),
    }),
  commitWorkflow: (workflowId: string, expectedVersion: number) =>
    request<Workflow>(`/api/v1/workflows/${encodeURIComponent(workflowId)}/actions/commit`, {
      method: "POST",
      body: JSON.stringify({ expected_version: expectedVersion }),
    }),
};
