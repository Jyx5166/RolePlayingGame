export interface ScriptPreview {
  script_id: string;
  title: string;
  total_stages: number;
  role_count: number;
  ai_agent_count: number;
  story_background: string;
  playable_roles: { role_id: string; role_name: string; public_identity: string }[];
}

export interface CatalogScript extends ScriptPreview {
  catalog_id: string;
  version: string;
  source: "builtin" | "imported";
  tags: string[];
  provenance?: {
    kind: "original" | "adaptation" | "unknown";
    creator: string;
    source: string;
  } | null;
}
