// The small −1…+1 axis of a finding: headline ρ as a dot, its 95 % CI as a whisker (as components/rho.py).
import { fmtRho, headline, RHO_AXIS_Y, RHO_HEIGHT, RHO_PAD, RHO_WIDTH, rhoColor, rhoX, type Finding } from "./rho";

export function RhoAxis({ finding }: { finding: Finding }) {
  const { rho, low, high } = headline(finding);
  if (rho === null || Number.isNaN(rho)) return null;
  const color = rhoColor(rho, finding.uncertain);
  const label = `ρ = ${fmtRho(rho, low, high)}${finding.uncertain ? " (neisté)" : ""}`;
  const hasCi = low !== null && high !== null && !Number.isNaN(low) && !Number.isNaN(high);
  return (
    <svg viewBox={`0 0 ${RHO_WIDTH} ${RHO_HEIGHT}`} width="100%" style={{ maxWidth: RHO_WIDTH }} role="img" aria-label={label} className="text-muted">
      <title>{label}</title>
      <line x1={rhoX(-1)} x2={rhoX(1)} y1={RHO_AXIS_Y} y2={RHO_AXIS_Y} stroke="currentColor" strokeOpacity={0.4} />
      <line x1={rhoX(0)} x2={rhoX(0)} y1={RHO_AXIS_Y - 6} y2={RHO_AXIS_Y + 6} stroke="currentColor" strokeOpacity={0.7} strokeDasharray="2 2" />
      {hasCi && <line x1={rhoX(low)} x2={rhoX(high)} y1={RHO_AXIS_Y} y2={RHO_AXIS_Y} stroke={color} strokeOpacity={0.55} strokeWidth={5} strokeLinecap="round" />}
      <circle cx={rhoX(rho)} cy={RHO_AXIS_Y} r={4.5} fill={color} />
      <text x={rhoX(-1) - RHO_PAD + 2} y={RHO_HEIGHT - 3} fontSize={14} textAnchor="start" fill="currentColor">−1</text>
      <text x={rhoX(0)} y={RHO_HEIGHT - 3} fontSize={14} textAnchor="middle" fill="currentColor">0</text>
      <text x={rhoX(1) + RHO_PAD - 2} y={RHO_HEIGHT - 3} fontSize={14} textAnchor="end" fill="currentColor">+1</text>
    </svg>
  );
}
