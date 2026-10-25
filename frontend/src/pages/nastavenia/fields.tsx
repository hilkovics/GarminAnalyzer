// Small form controls local to Nastavenia (labelled inputs in the design's style).
import { useId, type ReactNode } from "react";

import { cx } from "@/components/ui";

export const INPUT =
  "num w-full rounded-lg border border-line-strong bg-card-2 px-3 py-2 text-sm text-text placeholder:text-dim focus:outline-2 focus:outline-offset-1 focus:outline-accent disabled:opacity-50";

export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: ReactNode;
  children: (id: string) => ReactNode;
}) {
  const id = useId();
  return (
    <div className="min-w-0">
      <label htmlFor={id} className="mb-1 block text-xs text-muted">
        {label}
      </label>
      {children(id)}
      {hint && <p className="mt-1 text-xs text-muted">{hint}</p>}
    </div>
  );
}

/** A text input (type=text with a decimal keypad: Slovak users type a comma) with an optional unit suffix. */
export function TextField({
  label,
  value,
  onChange,
  unit,
  placeholder,
  hint,
  decimal = true,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  unit?: string;
  placeholder?: string;
  hint?: ReactNode;
  decimal?: boolean;
}) {
  return (
    <Field label={label} hint={hint}>
      {(id) => (
        <div className="relative">
          <input
            id={id}
            type="text"
            inputMode={decimal ? "decimal" : "text"}
            autoComplete="off"
            value={value}
            placeholder={placeholder}
            onChange={(e) => onChange(e.target.value)}
            className={cx(INPUT, unit && "pr-12")}
          />
          {unit && <span className="pointer-events-none absolute inset-y-0 right-3 flex items-center text-xs text-muted">{unit}</span>}
        </div>
      )}
    </Field>
  );
}

export function SelectField<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: { value: T; label: string }[];
  onChange: (value: T) => void;
}) {
  return (
    <Field label={label}>
      {(id) => (
        <select id={id} value={value} onChange={(e) => onChange(e.target.value as T)} className={INPUT}>
          {options.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      )}
    </Field>
  );
}

export function Checkbox({
  label,
  checked,
  onChange,
  disabled,
}: {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
}) {
  const id = useId();
  return (
    <div className="flex items-center gap-2">
      <input
        id={id}
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
        className="h-4 w-4 accent-[var(--accent)] disabled:opacity-50"
      />
      <label htmlFor={id} className={cx("text-sm", disabled && "text-dim")}>
        {label}
      </label>
    </div>
  );
}
