import { API_BASE_URL, getAuthorizationHeaders } from "@/lib/api/client";

export const eventTypes = [
  "conversation.updated",
  "conversation.deleted",
  "conversation.message.created",
  "conversation.message.completed",
  "task.created",
  "task.started",
  "task.progress",
  "task.completed",
  "task.failed",
  "task.interrupted",
  "task.rescheduled",
  "llm.request.started",
  "llm.request.completed",
  "tool.call.started",
  "tool.call.completed",
  "tool.call.failed",
  "skill.run.started",
  "skill.run.completed",
  "skill.run.failed",
  "plan.state_changed",
  "plan.step_state_changed",
  "report.generated",
  "workflow.created",
  "workflow.updated",
  "workflow.waiting_for_input",
  "workflow.ready_for_review",
  "workflow.reauth_required",
  "workflow.ready_for_commit",
  "workflow.committing",
  "workflow.succeeded",
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
  "operation.created",
  "operation.submitted",
  "operation.unknown",
  "operation.succeeded",
  "operation.failed",
  "security.reauth_failed",
  "security.control_bypass_attempt",
  "security.write_lock_activated",
] as const;

export function subscribeToConversation(
  conversationId: string,
  onEvent: (event: MessageEvent) => void,
  onConnectionChange: (connected: boolean) => void,
): () => void {
  const controller = new AbortController();

  function dispatchBlock(block: string) {
    let type = "message";
    const data: string[] = [];
    for (const line of block.split("\n")) {
      if (line.startsWith("event:")) type = line.slice(6).trim();
      if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
    }
    if (data.length > 0 && eventTypes.includes(type as (typeof eventTypes)[number])) {
      onEvent(new MessageEvent(type, { data: data.join("\n") }));
      if (type === "conversation.deleted") controller.abort();
    }
  }

  async function connect() {
    while (!controller.signal.aborted) {
      try {
        const authorization = await getAuthorizationHeaders();
        const response = await fetch(
          `${API_BASE_URL}/api/v1/events?conversation_id=${encodeURIComponent(conversationId)}`,
          {
            headers: { Accept: "text/event-stream", ...authorization },
            cache: "no-store",
            signal: controller.signal,
          },
        );
        if (response.status === 404) { onEvent(new MessageEvent("conversation.deleted", { data: "{}" })); controller.abort(); return; }
        if (!response.ok || !response.body) throw new Error(`SSE ${response.status}`);
        onConnectionChange(true);
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        while (!controller.signal.aborted) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true }).replaceAll("\r\n", "\n");
          let boundary = buffer.indexOf("\n\n");
          while (boundary >= 0) {
            dispatchBlock(buffer.slice(0, boundary));
            buffer = buffer.slice(boundary + 2);
            boundary = buffer.indexOf("\n\n");
          }
        }
      } catch {
        if (controller.signal.aborted) return;
      }
      onConnectionChange(false);
      await new Promise((resolve) => window.setTimeout(resolve, 1500));
    }
  }

  void connect();
  return () => {
    controller.abort();
    onConnectionChange(false);
  };
}
