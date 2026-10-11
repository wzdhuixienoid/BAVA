import type { AARequest, AAIntent, AAAccount } from "@/features/aa/types";
import type { components } from "@banking/api-client";
import { errorDisplay } from "../presentation/errors";

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
type SecurityStatus = components["schemas"]["SecurityStatus"];

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

let accessTokenProvider: () => Promise<string | null> = async () => null;

export function setAccessTokenProvider(provider: () => Promise<string | null>) {
  accessTokenProvider = provider;
}

export async function getAuthorizationHeaders(): Promise<Record<string, string>> {
  const token = await accessTokenProvider() ?? (typeof window !== "undefined" ? localStorage.getItem("banking-mock-session") : null);
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
    const detail = typeof rawDetail === "string" ? rawDetail : rawDetail?.message ?? rawDetail?.code ?? "请求失败";
    throw new Error(`请求失败（${response.status}）：${errorDisplay(detail)}`);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const api = {
  wealthAnalyze: (body: components["schemas"]["WealthAnalysisInput"]) => request<components["schemas"]["WealthAnalysis"]>("/api/v1/wealth/analysis", {method:"POST", body:JSON.stringify(body)}),
  wealthStatus: () => request<components["schemas"]["WealthFeatureStatus"]>("/api/v1/wealth/status"),
  wealthWorkflows: () => request<Workflow[]>("/api/v1/wealth/workflows"),
  wealthProducts: () => request<components["schemas"]["WealthProductResult"][]>("/api/v1/wealth/products"),
  wealthAccounts: () => request<components["schemas"]["AccountBalanceResult"][]>("/api/v1/wealth/accounts"),
  wealthPositions: () => request<components["schemas"]["WealthPositionResult"][]>("/api/v1/wealth/positions"),
  wealthOrders: () => request<components["schemas"]["WealthOrderResult"][]>("/api/v1/wealth/orders"),
  wealthAssessment: () => request<components["schemas"]["WealthAssessmentResult"] | null>("/api/v1/wealth/risk-assessments/current"),
  wealthQuestionnaire: () => request<{version: "mock-v1"; notice: string; questions: {label: string; options: string[]}[]}>("/api/v1/wealth/questionnaire"),
  wealthAssess: (body: components["schemas"]["AssessmentInput"]) => request<components["schemas"]["WealthAssessmentResult"]>("/api/v1/wealth/risk-assessments", {method:"POST", body:JSON.stringify(body)}),
  wealthCompare: (product_ids: string[]) => request<components["schemas"]["WealthProductResult"][]>("/api/v1/wealth/compare", {method:"POST", body:JSON.stringify({product_ids})}),
  wealthRecommend: (body: components["schemas"]["RecommendationInput"]) => request<components["schemas"]["WealthRecommendationResult"]>("/api/v1/wealth/recommendations", {method:"POST", body:JSON.stringify(body)}),
  wealthCreate: (body: components["schemas"]["WealthDraftInput"]) => request<Workflow>("/api/v1/wealth/workflows", {method:"POST", body:JSON.stringify(body)}),
  wealthEdit: (id: string, body: components["schemas"]["WealthEditInput"]) => request<Workflow>(`/api/v1/wealth/workflows/${encodeURIComponent(id)}/actions/edit`, {method:"POST", body:JSON.stringify(body)}),
  wealthDocument: (id: string) => request<components["schemas"]["WealthKnowledgeResult"]>(`/api/v1/wealth/documents/${encodeURIComponent(id)}`),

  listNotifications: (offset = 0) => request<components["schemas"]["NotificationInbox"]>(`/api/v1/notifications?offset=${offset}`),
  readNotification: (id: string) => request<components["schemas"]["Notification"]>(`/api/v1/notifications/${encodeURIComponent(id)}/read`, { method: "POST" }),
  deleteNotification: (id: string) => request<void>(`/api/v1/notifications/${encodeURIComponent(id)}`, { method: "DELETE" }),
  listAA: () => request<AARequest[]>("/api/v1/aa-requests"),
  getAA: (id:string) => request<AARequest>(`/api/v1/aa-requests/${encodeURIComponent(id)}`),
  aaAccounts: () => request<AAAccount[]>("/api/v1/aa-accounts"),
  updateAA: (id:string, expected_version:number, intent:AAIntent, collection_account_id:string, deadline:string) => request<AARequest>(`/api/v1/aa-requests/${encodeURIComponent(id)}`, {method:"PATCH",body:JSON.stringify({expected_version,intent,collection_account_id,deadline})}),
  publishAA: (id:string, expected_version:number) => request<AARequest>(`/api/v1/aa-requests/${encodeURIComponent(id)}/actions/publish`, {method:"POST",body:JSON.stringify({expected_version})}),
  payAA: (id:string, expected_version:number, source_account_id:string) => request<Workflow>(`/api/v1/aa-shares/${encodeURIComponent(id)}/actions/pay`, {method:"POST",body:JSON.stringify({expected_version,source_account_id})}),
  closeAAShare: (id:string, action:"cancel"|"reject", expected_version:number) => request<AARequest>(`/api/v1/aa-shares/${encodeURIComponent(id)}/actions/${action}`, {method:"POST",body:JSON.stringify({expected_version})}),
  mockSessions: () => request<{enabled:boolean;current_user_id:string;identities:{name:string;identity:string}[]}>("/api/v1/mock-sessions"),
  mockLogin: (identity:string) => request<{access_token:string}>("/api/v1/mock-sessions", {method:"POST",body:JSON.stringify({identity})}),
  listSchedules: () => request<components["schemas"]["ScheduledTransfer"][]>("/api/v1/scheduled-transfers"),
  getSchedule: (id: string) => request<components["schemas"]["ScheduledTransfer"]>(`/api/v1/scheduled-transfers/${encodeURIComponent(id)}`),
  scheduleAction: (id: string, action: "authorize" | "cancel" | "cancel-series" | "delete", expected_version: number) => request<components["schemas"]["ScheduledTransfer"]>(`/api/v1/scheduled-transfers/${encodeURIComponent(id)}/actions/${action}`, {method: "POST", body: JSON.stringify({expected_version})}),
  setExecutionTime: (id: string, execution_time_text: string, expected_version: number) => request<Workflow>(`/api/v1/workflows/${encodeURIComponent(id)}/actions/set-execution-time`, {method: "POST", body: JSON.stringify({execution_time_text, expected_version})}),
  getTaskAudit: (taskId: string) => request<components["schemas"]["AuditTrace"]>(
    `/api/v1/tasks/${encodeURIComponent(taskId)}/audit`,
  ),
  getDashboard: (month: string) => request<components["schemas"]["DashboardSnapshot"]>(
    `/api/v1/dashboard?month=${encodeURIComponent(month)}`,
  ),
  listPlans: (conversationId: string) => request<components["schemas"]["Plan"][]>(
    `/api/v1/plans?conversation_id=${encodeURIComponent(conversationId)}`,
  ),
  takeOverPlan: (planId: string) => request<components["schemas"]["Plan"]>(
    `/api/v1/plans/${encodeURIComponent(planId)}/actions/take-over`, { method: "POST" },
  ),
  resumePlan: (planId: string) => request<components["schemas"]["Plan"]>(
    `/api/v1/plans/${encodeURIComponent(planId)}/actions/resume`, { method: "POST" },
  ),
  rollbackPlan: (planId: string, stepId: string) => request<components["schemas"]["Plan"]>(
    `/api/v1/plans/${encodeURIComponent(planId)}/actions/rollback`, {
      method: "POST", body: JSON.stringify({ target_step_id: stepId }),
    },
  ),
  getSecurityStatus: () => request<SecurityStatus>("/api/v1/security/status"),
  listPayees: (query?: string, offset = 0) => request<components["schemas"]["PayeeSummary"][]>(
    `/api/v1/payees?offset=${offset}${query ? `&query=${encodeURIComponent(query)}` : ""}`),
  createPayee: (body: components["schemas"]["PayeeCreate"]) => request<components["schemas"]["PayeeSummary"]>("/api/v1/payees", { method: "POST", body: JSON.stringify(body) }),
  setTransferRemark: (id: string, remark: string, expected_version: number) => request<Workflow>(`/api/v1/workflows/${encodeURIComponent(id)}/actions/set-remark`, { method: "POST", body: JSON.stringify({ remark, expected_version }) }),
  updatePayee: (id: string, body: components["schemas"]["PayeeUpdate"]) => request<components["schemas"]["PayeeSummary"]>(`/api/v1/payees/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(body) }),
  deletePayee: (id: string) => request<void>(`/api/v1/payees/${encodeURIComponent(id)}`, { method: "DELETE" }),
  deleteConversation: (id: string) => request<void>(`/api/v1/conversations/${encodeURIComponent(id)}`, { method: "DELETE" }),
  renameConversation: (id: string, title: string) => request<Conversation>(
    `/api/v1/conversations/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify({ title }) },
  ),
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
  listTaskEvents: (taskId: string) =>
    request<components["schemas"]["Event"][]>(`/api/v1/tasks/${encodeURIComponent(taskId)}/events`),
  listWorkflows: (conversationId?: string) =>
    request<Workflow[]>(
      `/api/v1/workflows${conversationId ? `?conversation_id=${encodeURIComponent(conversationId)}` : ""}`,
    ),
  getWorkflow: (workflowId: string) =>
    request<Workflow>(`/api/v1/workflows/${encodeURIComponent(workflowId)}`),
  selectPayee: (workflowId: string, payeeId: string, expectedVersion: number, recipientQuery?: string) =>
    request<Workflow>(`/api/v1/workflows/${encodeURIComponent(workflowId)}/actions/select-payee`, {
      method: "POST",
      body: JSON.stringify({ payee_id: payeeId, expected_version: expectedVersion, recipient_query: recipientQuery }),
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
  listReports: (conversationId?: string, limit = 20, offset = 0, deleted = false) => {
    const query = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    if (conversationId) query.set("conversation_id", conversationId);
    if (deleted) query.set("deleted", "true");
    return request<ReportListItem[]>(`/api/v1/reports?${query.toString()}`);
  },
  deleteReport: (reportId: string) => request<void>(`/api/v1/reports/${encodeURIComponent(reportId)}`, { method: "DELETE" }),
  restoreReport: (reportId: string) => request<void>(`/api/v1/reports/${encodeURIComponent(reportId)}/restore`, { method: "POST" }),
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
  cancelSubscription: (subscriptionId: string, expectedVersion: number, idempotencyKey: string) =>
    request<SubscriptionItem>(`/api/v1/subscriptions/${encodeURIComponent(subscriptionId)}/cancel`, {
      method: "POST",
      body: JSON.stringify({ confirmed: true, expected_version: expectedVersion, idempotency_key: idempotencyKey }),
    }),
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
