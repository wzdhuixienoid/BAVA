export function TaskProgress({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <p className="mt-2 rounded bg-blue-50 px-2 py-1 text-xs text-blue-700" aria-live="polite">
      {message}
    </p>
  );
}
