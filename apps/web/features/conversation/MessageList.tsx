import type { components } from "@banking/api-client";

type Message = components["schemas"]["Message"];

export function MessageList({ messages }: { messages: Message[] }) {
  return (
    <div className="flex flex-1 flex-col gap-3 overflow-y-auto p-6">
      {messages.length === 0 && (
        <div className="m-auto max-w-md text-center text-sm text-slate-500">
          Send a message. The deterministic bootstrap runtime will acknowledge it without an LLM.
        </div>
      )}
      {messages.map((message) => {
        const user = message.role === "USER";
        return (
          <article
            key={message.message_id}
            className={`max-w-[80%] rounded-xl px-4 py-3 text-sm ${
              user ? "ml-auto bg-cyan-600 text-white" : "bg-slate-100 text-slate-800"
            }`}
          >
            <p className="mb-1 text-[10px] font-semibold uppercase tracking-wider opacity-65">
              {message.role}
            </p>
            <p className="whitespace-pre-wrap">{message.content}</p>
          </article>
        );
      })}
    </div>
  );
}

