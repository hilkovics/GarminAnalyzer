// A tiny Markdown renderer for the weekly AI report (headings, lists, bold/italic, paragraphs). Text only:
// no HTML from the report is ever injected.
import type { ReactNode } from "react";

function inline(text: string): ReactNode[] {
  const parts = text.split(/(\*\*[^*]+\*\*|\*[^*]+\*)/g);
  return parts.map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**")) return <strong key={i}>{part.slice(2, -2)}</strong>;
    if (part.startsWith("*") && part.endsWith("*") && part.length > 2) return <em key={i}>{part.slice(1, -1)}</em>;
    return part;
  });
}

export function Markdown({ text }: { text: string }) {
  const blocks: ReactNode[] = [];
  let list: string[] = [];
  const flush = () => {
    if (list.length) {
      blocks.push(
        <ul key={blocks.length} className="my-2 list-disc space-y-1 pl-5">
          {list.map((item, i) => (
            <li key={i}>{inline(item)}</li>
          ))}
        </ul>,
      );
      list = [];
    }
  };
  for (const raw of text.split("\n")) {
    const line = raw.trimEnd();
    const bullet = /^\s*[-*]\s+(.*)$/.exec(line);
    if (bullet) {
      list.push(bullet[1]);
      continue;
    }
    flush();
    const heading = /^(#{1,4})\s+(.*)$/.exec(line);
    if (heading) {
      blocks.push(
        <h3 key={blocks.length} className="mt-4 mb-1 text-base font-bold first:mt-0">
          {inline(heading[2])}
        </h3>,
      );
    } else if (line.trim()) {
      blocks.push(
        <p key={blocks.length} className="my-2">
          {inline(line)}
        </p>,
      );
    }
  }
  flush();
  return <div className="text-sm leading-relaxed">{blocks}</div>;
}
