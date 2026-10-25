// The list as a clickable table (desktop) and as cards (phones). Each row/card links to /aktivity/<id>.
import { Link, useNavigate } from "@tanstack/react-router";

import type { Schemas } from "@/api/client";
import { fmtDate, fmtDuration, fmtKm, fmtLoad, fmtSpeed, sportLabel } from "@/lib/format";
import { SPORT_COLORS } from "@/lib/labels";

import type { ListSearch } from "./lib";

type Item = Schemas["ActivitySummaryDTO"];

const sportText = (a: Item) => sportLabel(a.sport) + (a.is_commute ? " · dochádzka" : "");
const detailSearch = (search: ListSearch) => ({ ...search, page: search.page && search.page > 1 ? search.page : undefined }) as never;

function SportDot({ sport }: { sport: string }) {
  return <span aria-hidden className="inline-block h-2 w-2 shrink-0 rounded-full" style={{ background: SPORT_COLORS[sport] ?? "var(--neutral)" }} />;
}

export function ActivityTable({ items, search }: { items: Item[]; search: ListSearch }) {
  const navigate = useNavigate();
  const head = ["Dátum", "Šport", "Názov", "Trvanie", "Vzdialenosť", "Tempo / rýchlosť", "Záťaž"];
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr className="border-b border-line-strong text-left">
            {head.map((h, i) => (
              <th key={h} className={`label px-4 py-3 ${i >= 3 ? "text-right" : ""}`}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {items.map((a) => (
            <tr
              key={a.id}
              onClick={() => void navigate({ to: "/aktivity/$activityId", params: { activityId: String(a.id) }, search: detailSearch(search) })}
              className="cursor-pointer border-b border-line last:border-0 hover:bg-card-2"
            >
              <td className="num whitespace-nowrap px-4 py-2.5">{fmtDate(a.local_date)}</td>
              <td className="whitespace-nowrap px-4 py-2.5">
                <span className="inline-flex items-center gap-2">
                  <SportDot sport={a.sport} />
                  {sportText(a)}
                </span>
              </td>
              <td className="max-w-[22rem] truncate px-4 py-2.5">
                <Link
                  to="/aktivity/$activityId"
                  params={{ activityId: String(a.id) }}
                  search={detailSearch(search)}
                  onClick={(e) => e.stopPropagation()}
                  className="hover:text-accent hover:underline"
                >
                  {a.name || "–"}
                </Link>
              </td>
              <td className="num px-4 py-2.5 text-right">{fmtDuration(a.duration_s)}</td>
              <td className="num whitespace-nowrap px-4 py-2.5 text-right">{fmtKm(a.distance_m, 2)}</td>
              <td className="num whitespace-nowrap px-4 py-2.5 text-right">{fmtSpeed(a.avg_speed, a.sport)}</td>
              <td className="num whitespace-nowrap px-4 py-2.5 text-right">{fmtLoad(a.load_primary, a.load_method, a.low_confidence)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function ActivityCards({ items, search }: { items: Item[]; search: ListSearch }) {
  return (
    <ul className="divide-y divide-line">
      {items.map((a) => (
        <li key={a.id}>
          <Link to="/aktivity/$activityId" params={{ activityId: String(a.id) }} search={detailSearch(search)} className="block px-4 py-3 hover:bg-card-2">
            <div className="flex items-baseline justify-between gap-3">
              <span className="min-w-0 truncate font-semibold">{a.name || "–"}</span>
              <span className="num shrink-0 text-xs text-muted">{fmtDate(a.local_date)}</span>
            </div>
            <div className="mt-0.5 flex items-center gap-2 text-xs text-muted">
              <SportDot sport={a.sport} />
              {sportText(a)}
            </div>
            <div className="num mt-2 grid grid-cols-4 gap-2 text-sm">
              <span>{fmtDuration(a.duration_s)}</span>
              <span>{fmtKm(a.distance_m, 2)}</span>
              <span>{fmtSpeed(a.avg_speed, a.sport)}</span>
              <span className="text-right">{fmtLoad(a.load_primary, a.load_method, a.low_confidence)}</span>
            </div>
          </Link>
        </li>
      ))}
    </ul>
  );
}
