import type { ScriptPreview } from "./scripts";

export interface AuthoringStep {
  step_id: string;
  label: string;
  status: "pending" | "running" | "completed" | "failed" | "interrupted";
  error?: string;
}

export interface AuthoringValidation {
  passed: boolean;
  checks: { code: string; label: string; status: "passed" | "failed" | "warning"; message: string; path?: string }[];
  errors: string[];
  warnings: string[];
}

export interface SemanticReview {
  status: "passed" | "failed" | "not_run" | "running" | "incomplete";
  summary: string;
  issues?: { severity: "error" | "warning"; code: string; message: string; path?: string }[];
}

export type AuthoringPreview = Partial<ScriptPreview> & {
  authoring_validation?: AuthoringValidation;
  semantic_review?: SemanticReview;
  semantic_required?: boolean;
};

export interface AuthoringJob {
  job_id: string;
  status: "queued" | "generating" | "validating" | "preview" | "failed" | "interrupted" | "published";
  mode?: "import" | "ai";
  input?: { source_job_id?: string | null; title?: string; tags?: string[]; topic?: string };
  catalog_id?: string | null;
  steps?: AuthoringStep[];
  error?: string;
  draft?: Record<string, unknown> | null;
  preview?: AuthoringPreview | null;
  can_publish?: boolean;
}
