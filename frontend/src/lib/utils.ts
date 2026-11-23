import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export const cn = (...inputs: ClassValue[]) => twMerge(clsx(inputs));

export const fmtNumber = (n: number | null | undefined) =>
  n === null || n === undefined ? "—" : new Intl.NumberFormat().format(n);

/** The backend stores naive UTC datetimes and serialises them without an offset; treat those as UTC. */
export const parseUtc = (v: string): Date => new Date(/(Z|[+-]\d{2}:?\d{2})$/.test(v) || !/T/.test(v) ? v : `${v}Z`);

export const fmtDate = (v: string | null | undefined) => {
  if (!v) return "—";
  const d = parseUtc(v);
  return Number.isNaN(d.getTime()) ? v : d.toLocaleString();
};

export const humanize = (s: string | null | undefined) =>
  s ? s.replace(/[_-]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()) : "—";
