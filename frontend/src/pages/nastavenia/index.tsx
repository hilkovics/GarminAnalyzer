// Nastavenia: athlete, thresholds and zones (with threshold proposals), sync and diagnostics.
import { useState } from "react";

import { useApi, type Schemas } from "@/api/client";
import { Card, Notice, PageHeader, QueryState, cx } from "@/components/ui";

import { AthleteForm } from "./AthleteForm";
import { DiagnosticsPanel } from "./Diagnostics";
import { Proposals } from "./Proposals";
import { SyncPanel } from "./Sync";
import { AddThreshold, ThresholdHistory, ZonePreview } from "./Thresholds";

const TABS = [
  { id: "athlete", label: "Atlét" },
  { id: "thresholds", label: "Prahy a zóny" },
  { id: "sync", label: "Sync a diagnostika" },
] as const;
type TabId = (typeof TABS)[number]["id"];

function Tabs({ value, onChange }: { value: TabId; onChange: (id: TabId) => void }) {
  return (
    <div role="tablist" aria-label="Sekcie nastavení" className="mb-4 flex gap-1 overflow-x-auto border-b border-line">
      {TABS.map((tab) => (
        <button
          key={tab.id}
          type="button"
          role="tab"
          id={`tab-${tab.id}`}
          aria-selected={tab.id === value}
          aria-controls={`panel-${tab.id}`}
          onClick={() => onChange(tab.id)}
          className={cx(
            "-mb-px whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium transition-colors",
            tab.id === value ? "border-accent text-text" : "border-transparent text-muted hover:text-text",
          )}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}

function Thresholds({ cfg, onSaved }: { cfg: Schemas["SettingsDTO"]; onSaved: (message: string) => void }) {
  return (
    <div className="flex flex-col gap-4">
      <Card title="História prahov">
        <ThresholdHistory cfg={cfg} />
      </Card>
      <AddThreshold cfg={cfg} onSaved={onSaved} />
      <ZonePreview cfg={cfg} />
      <Proposals onSaved={onSaved} />
    </div>
  );
}

export default function Page() {
  const [tab, setTab] = useState<TabId>("athlete");
  const [flash, setFlash] = useState<string | null>(null);
  const settings = useApi<Schemas["SettingsDTO"]>("/settings");
  const saved = (message: string) => setFlash(message);

  return (
    <>
      <PageHeader title="Nastavenia" />
      {flash && (
        <div className="mb-4" role="status">
          <Notice tone="green">{flash}</Notice>
        </div>
      )}
      <Tabs
        value={tab}
        onChange={(id) => {
          setTab(id);
          setFlash(null);
        }}
      />
      <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
        {tab === "sync" ? (
          <div className="flex flex-col gap-4">
            <SyncPanel />
            <DiagnosticsPanel />
          </div>
        ) : (
          <QueryState query={settings}>
            {(cfg) =>
              tab === "athlete" ? (
                <AthleteForm athlete={cfg.athlete} onSaved={saved} />
              ) : (
                <Thresholds cfg={cfg} onSaved={saved} />
              )
            }
          </QueryState>
        )}
      </div>
    </>
  );
}
