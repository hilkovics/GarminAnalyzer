// Aktivity: filterable, paged list (table on desktop, cards on phones); a click opens /aktivity/<id>.
import { useNavigate, useSearch } from "@tanstack/react-router";

import { useApi, type Schemas } from "@/api/client";
import { Button, Card, Notice, PageHeader, QueryState, Segmented } from "@/components/ui";

import { ActivityCards, ActivityTable } from "./ActivityRows";
import type { ListSearch } from "./lib";

const PAGE_SIZE = 25;
const SPORTS = [
  { value: "all", label: "Všetky" },
  { value: "run", label: "Beh" },
  { value: "bike", label: "Bicykel" },
  { value: "other", label: "Iné" },
];
const text = (v: unknown): string | undefined => (typeof v === "string" && v ? v : undefined);

/** The filters live in the URL (?from&to&sport&page) so the back link of a detail returns to the same view. */
export function readSearch(raw: Record<string, unknown>): ListSearch & { page: number } {
  const page = Number(raw.page);
  return { from: text(raw.from), to: text(raw.to), sport: text(raw.sport), page: Number.isInteger(page) && page > 1 ? page : 1 };
}

function DateField({ id, label, value, onChange }: { id: string; label: string; value?: string; onChange: (v: string) => void }) {
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-xs text-muted">
        {label}
      </label>
      <input
        id={id}
        type="date"
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value)}
        className="num h-[34px] rounded-lg border border-line-strong bg-card-2 px-2.5 text-sm text-text"
      />
    </div>
  );
}

export default function ActivitiesPage() {
  const navigate = useNavigate();
  const search = readSearch(useSearch({ strict: false }) as Record<string, unknown>);
  const set = (patch: Partial<ListSearch>) => {
    const next = { ...search, page: 1, ...patch };
    void navigate({
      to: "/aktivity",
      search: { from: next.from || undefined, to: next.to || undefined, sport: next.sport || undefined, page: next.page > 1 ? next.page : undefined } as never,
      replace: true,
    });
  };
  const invalid = Boolean(search.from && search.to && search.from > search.to);
  const query = useApi<Schemas["ActivityListDTO"]>(
    "/activities",
    { from: search.from, to: search.to, sport: search.sport, page: search.page, page_size: PAGE_SIZE },
    { enabled: !invalid, keepPrevious: true },
  );
  return (
    <>
      <PageHeader
        title="Aktivity"
        right={
          <div className="flex flex-wrap items-end gap-3">
            <DateField id="act-from" label="Od" value={search.from} onChange={(v) => set({ from: v })} />
            <DateField id="act-to" label="Do" value={search.to} onChange={(v) => set({ to: v })} />
            <Segmented label="Šport" value={search.sport ?? "all"} options={SPORTS} onChange={(v) => set({ sport: v === "all" ? undefined : v })} />
          </div>
        }
      />
      {invalid ? (
        <Notice tone="red">Dátum „Od“ je neskôr ako „Do“.</Notice>
      ) : (
        <QueryState query={query}>{(list) => <ListBody list={list} search={search} onPage={(page) => set({ page })} />}</QueryState>
      )}
    </>
  );
}

function ListBody({ list, search, onPage }: { list: Schemas["ActivityListDTO"]; search: ListSearch; onPage: (page: number) => void }) {
  const lastPage = Math.max(1, Math.ceil(list.total / list.page_size));
  if (!list.items.length) {
    return (
      <Card>
        <p className="text-sm text-muted">Žiadne aktivity pre zvolený filter.</p>
        {list.total > 0 && list.page > 1 && (
          <div className="mt-3">
            <Button variant="secondary" onClick={() => onPage(1)}>
              Späť na prvú stranu
            </Button>
          </div>
        )}
      </Card>
    );
  }
  return (
    <div className="flex flex-col gap-3">
      <Card padded={false}>
        <div className="hidden md:block">
          <ActivityTable items={list.items} search={search} />
        </div>
        <div className="md:hidden">
          <ActivityCards items={list.items} search={search} />
        </div>
        <div className="flex items-center justify-between gap-3 border-t border-line px-4 py-3 text-sm">
          <Button variant="ghost" disabled={list.page <= 1} onClick={() => onPage(list.page - 1)}>
            ‹ Novšie
          </Button>
          <span className="text-center text-muted">
            Strana <b className="num text-text">{list.page}</b> z <b className="num text-text">{lastPage}</b> · {list.total} aktivít
          </span>
          <Button variant="ghost" disabled={list.page >= lastPage} onClick={() => onPage(list.page + 1)}>
            Staršie ›
          </Button>
        </div>
      </Card>
      <p className="text-xs text-muted">
        ⚠ = neznáma alebo nízko spoľahlivá záťaž. Dochádzka (jazda kratšia ako 25 min) sa ráta do únavy, nie do tréningu.
        Klikni na aktivitu pre detail.
      </p>
    </div>
  );
}
