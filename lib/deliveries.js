/** Canonical Source delivery sequence and pipeline stage names (single source of truth for the API). */
export const STAGES = ["ingest", "extract", "transform", "load", "validate"];
export const DELIVERIES = [
  "initial",
  ...Array.from({ length: 9 }, (_, i) => "incremental_" + String(i + 1).padStart(2, "0"))
];
