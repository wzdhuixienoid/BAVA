import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";

export function MarkdownMessage({ content }: { content: string }) {
  return (
    <div className="message-markdown min-w-0">
      <Markdown
        remarkPlugins={[remarkGfm]}
        skipHtml
        components={{
          a: ({ children, href, title }) => (
            <a href={href} title={title} target="_blank" rel="noopener noreferrer">{children}</a>
          ),
          table: ({ children }) => (
            <div className="overflow-x-auto"><table>{children}</table></div>
          ),
        }}
      >
        {content}
      </Markdown>
    </div>
  );
}
