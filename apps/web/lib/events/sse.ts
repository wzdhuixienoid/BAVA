import { API_BASE_URL } from "@/lib/api/client";

export const bootstrapEventTypes = [
  "conversation.message.created",
  "conversation.message.completed",
  "task.created",
  "task.started",
  "task.completed",
  "task.failed",
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
  bootstrapEventTypes.forEach((type) => source.addEventListener(type, onEvent));
  return () => {
    bootstrapEventTypes.forEach((type) => source.removeEventListener(type, onEvent));
    source.close();
    onConnectionChange(false);
  };
}

