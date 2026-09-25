import { API_BASE_URL } from "@/lib/api/client";

export const eventTypes = [
  "conversation.message.created",
  "conversation.message.completed",
  "task.created",
  "task.started",
  "task.progress",
  "task.completed",
  "task.failed",
  "report.generated",
  "workflow.created",
  "workflow.updated",
  "workflow.waiting_for_input",
  "workflow.ready_for_review",
  "workflow.reauth_required",
  "workflow.ready_for_commit",
  "workflow.failed",
  "workflow.cancelled",
  "approval.created",
  "approval.approved",
  "approval.invalidated",
  "approval.expired",
  "reauth.challenge.created",
  "reauth.verified",
  "reauth.failed",
  "reauth.expired",
  "reauth.invalidated",
] as const;

export function subscribeToConversation(
  conversationId: string,
  onEvent: (event: MessageEvent) => void,
  onConnectionChange: (connected: boolean) => void,
): () => void {
  const source = new EventSource(
    `${API_BASE_URL}/api/v1/events?conversation_id=${encodeURIComponent(conversationId)}`,
  );
  source.onopen = () => onConnectionChange(true);
  source.onerror = () => onConnectionChange(false);
  eventTypes.forEach((type) => source.addEventListener(type, onEvent));
  return () => {
    eventTypes.forEach((type) => source.removeEventListener(type, onEvent));
    source.close();
    onConnectionChange(false);
  };
}
