export interface AICluster { cluster_id: string; source_cluster_id: string; label: string; membership_strength: number | null; post_ids: string[] }
export interface AIClaim { claim_id: string; claim_text: string; cluster_id: string | null; stance: string; confidence: number | null; post_ids: string[] }
export interface AIContext { analyzed_post_count: number; total_post_count: number; clusters?: AICluster[]; unassigned_post_count?: number; claims: AIClaim[]; stance_counts: Record<string, number> }
export type FusionStatus = 'pending' | 'partial' | 'enriched'
export interface Post { issue_matches?: { post_id: string; source: string; rule_id: string; matched_terms: string[]; target_post_id?: string }[]; id: string; account_id: string; created_at: string; text: string; urls: string[]; narrative_id: string | null; stance_hint: string | null; language: string | null; ai_status?: 'pending' | 'received' | 'disabled'; ai_claims?: AIClaim[]; ai_clusters?: AICluster[] }
export interface Alert { evidence_posts?: Post[]; cross_issue?: boolean; id: string; kind: 'repeated_url_coshare' | 'hourly_diffusion_spike' | 'behavior_coordination' | 'resource_burst'; phase?: 'active' | 'historical'; label: string; priority: string; summary: string; reason_codes: string[]; reason_labels: string[]; evidence_post_ids: string[]; account_ids: string[]; metrics: Record<string, number | string | number[]>; episodes?: { start: string; end: string; url: string; post_ids: string[] }[]; network_score?: number; score_components?: Record<string, number | null>; fusion_status?: FusionStatus; first_seen?: string; last_seen?: string; ai_context?: AIContext }
export interface Edge { id: string; source: string; target: string; kind: 'co_share' | 'quotes' | 'reposts' | 'replies_to'; evidence_post_ids: string[]; alert_ids: string[]; weight: number }
export interface Narrative { kind?: 'cluster' | 'resource'; id: string; label: string; stance_hint: string | null; post_count: number; evidence_post_ids: string[] }
// ANTI_FIMI_SOURCE_TRACE_V1
export interface SourceTracePost { post_id: string; account_id: string; created_at: string; text: string }
export interface SourceTraceRoot extends SourceTracePost { reachable_posts: number; observed_depth: number; upstream_outside_scope: boolean; upstream_not_collected: boolean }
export interface SourceTrace {
  earliest_observed: SourceTracePost | null; leading_root: SourceTraceRoot | null; root_candidates: SourceTraceRoot[];
  nodes: (SourceTracePost & { depth: number })[];
  edges: { source: string; target: string; kind: 'quotes' | 'reposts' | 'replies_to' }[];
  linked_post_count: number; total_posts: number; observed_edge_count: number; observed_max_depth: number;
  outside_scope_references: number; unavailable_references: number; time_inconsistent_references: number;
  claim: 'observed_reference_chain' | 'chronological_only' | 'empty'; limitations: string;
}
export interface EventCase {
  source_trace?: SourceTrace;
  spread?: SpreadMetrics;
  id: string; title: string; summary: string; first_seen: string; last_seen: string; post_count: number; account_count: number; alert_count: number; languages: string[]; priority: 'review_high' | 'review_medium' | 'none'; basis: string[];
  posts: Post[]; alerts: Alert[]; network: { nodes: { id: string; label: string; post_count: number; stance_hints: string[] }[]; edges: Edge[] };
  hourly: { time: string; count: number; account_count: number; baseline: number | null; partial: boolean }[]; narratives: Narrative[];
  source?: 'behavior' | 'local_preview' | 'ai' | 'resource' | 'issue'; analysis_mode?: 'no-ai'; child_alert_ids?: string[]; related_case_ids?: string[]; fusion_status?: FusionStatus; network_score?: number; score_components?: Record<string, number | null>; ai_context?: AIContext; response_plans?: ResponsePlan[];
}
export interface Pipeline { mode: 'external-ai' | 'local-preview' | 'no-ai'; resource_group_count?: number; issue_count?: number; raw_post_count: number; raw_account_count: number; behavior_post_count: number; behavior_pending_count: number; ai_received_count: number; ai_pending_count: number; ai_status: 'waiting' | 'partial' | 'ready' | 'disabled'; behavior_as_of: string | null; behavior_window_hours: number; score_calibrated: false }
export interface DashboardData {
  session?: { id: string; started_at: string | null; requires_session_id: boolean };
  spread_clock?: { mode: 'live' | 'replay'; as_of: string };
  schema_version: '1.0'; snapshot_id: string; generated_at: string; analysis_as_of: string; analyzed_at: string; data_mode: 'lexical-demo' | 'semantic' | 'rule-based';
  feed: { status: 'watching' | 'idle' | 'error'; error: string | null; last_ingested_at: string | null; collector?: { status: 'starting' | 'running' | 'error' | 'stopped'; baseline_ready: boolean; source_url: string; session_id: string; sent: number; pending: number; rejected: number; error: string | null } };
  summary: { case_count: number; post_count: number; account_count: number; alert_count: number; pending_post_count: number };
  cases: EventCase[]; issue_cases?: EventCase[]; issue_unclassified_posts?: Post[]; unassigned_alert_cases?: EventCase[]; limitations: string[];
  scenario_catalog?: ScenarioType[]; scenario_candidates?: ResponsePlan[]; pipeline?: Pipeline; investigations?: EventCase[]; unlinked_posts?: Post[]; global_signals_count?: number; early_alerts_count?: number; playbook?: PlaybookStatus; playbook_raw_matches?: ResponsePlan[];
}
export interface SpreadMetrics {
  bucket_seconds?: number; history_span_seconds?: number; history_start?: string | null; history_end?: string;
  state: 'insufficient' | 'low_volume' | 'steady' | 'accelerating' | 'surging' | 'declining';
  as_of: string; window_minutes: 5; current_post_count: number; previous_post_count: number;
  current_account_count: number; previous_account_count: number; baseline_ready: boolean;
  history: { time: string; end?: string; post_count: number; account_count: number; within_observed_range: boolean; observed?: boolean; partial?: boolean; partial_last?: boolean }[];
  basis: string; calibrated: false;
}
export interface ResponseAction { order: number; phase: string; owner: string; precondition: string; action: string; output: string; done_when: string; authority: string }
export interface ResponsePlan { observable_label?: string; missing_checks?: string[]; evidence_level?: string; evidence_posts?: Post[]; cross_case?: boolean; propaganda_status?: string; review_rules_hash?: string; id: string; entity_id: string; scenario_id: string; title: string; state: 'candidate'; risk: 'UNASSESSED'; potential_risk: string; rule_id: string; reason: string; evidence_post_ids: string[]; alert_ids: string[]; observations: Record<string, unknown>; next_verification: string; actions: ResponseAction[]; workbook_hash: string; as_of: string; automatic_execution: false }
export interface ScenarioType { scenario_id: string; title: string; match_mode: 'text_review' | 'behavior' | 'manual'; observable_label: string; missing_inputs: string[]; required_evidence: string[]; next_verification: string; actions: ResponseAction[] }
export interface PlaybookStatus { review_status?: 'ready' | 'error'; review_error?: string; review_rule_count?: number; review_rules_hash?: string; status: 'ready' | 'error' | 'not_loaded'; path?: string; workbook_hash?: string | null; scenario_count?: number; enabled_rule_count?: number; effective_enabled_rule_count?: number; disabled_rule_ids?: string[]; error?: string | null }
