// Core domain models mirroring backend schemas

export interface Review {
  id: string;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';
  pr_url?: string;
  pr_number?: number;
  pr_title?: string;
  pr_author?: string;
  pr_author_email?: string;
  source_branch?: string;
  target_branch?: string;
  author?: string;
  workspace?: string;
  repo_slug?: string;
  bitbucket_workspace?: string;
  bitbucket_repo_slug?: string;
  jira_key?: string;
  jira_url?: string;
  current_agent?: string;
  progress_percent: number;
  risk_score?: number;
  overall_recommendation?: string;
  error_message?: string;
  created_at: string;
  updated_at: string;
}

export interface Finding {
  id: string;
  review_id: string;
  agent_name: string;
  severity: 'critical' | 'high' | 'medium' | 'low' | 'info';
  category: 'requirement' | 'code_quality' | 'sql_performance' | 'security' | 'refactoring' | 'test_coverage';
  file_path?: string;
  line_number?: number;
  title: string;
  description: string;
  evidence?: string;
  recommendation: string;
  review_comment: string;
  pr_comment?: string;
  approval_status: 'pending' | 'approved' | 'rejected';
  edited_comment?: string;
  published: boolean;
  origin?: 'introduced_by_pr' | 'modified_by_pr' | 'worsened_by_pr' | 'pre_existing' | 'contextual' | 'unknown';
  change_scope?: 'changed' | 'unchanged' | 'both';
  classification?: 'finding' | 'recommendation';
  affected_by_pr?: boolean;
  created_at: string;
}

export interface ReviewSummary {
  review_id: string;
  risk_score?: number;
  overall_recommendation?: string;
  total_findings: number;
  findings_by_severity: Record<string, number>;
  findings_by_category: Record<string, number>;
  agent_summaries: AgentSummary[];
  summary_text?: string;
}

export interface AgentSummary {
  agent_name: string;
  status: string;
  findings_count: number;
  duration_seconds?: number;
}

export interface AppSettings {
  bitbucket_workspace?: string;
  jira_base_url?: string;
  jira_email?: string;
  ai_provider: string;
  has_bitbucket_token: boolean;
  has_jira_token: boolean;
  has_openai_key: boolean;
  has_anthropic_key: boolean;
  has_gemini_key: boolean;
}

export interface ProgressEvent {
  review_id: string;
  status: string;
  current_agent?: string;
  progress_percent: number;
  log?: LogEntry;
}

export interface LogEntry {
  timestamp: string;
  agent: string;
  message: string;
  level: 'info' | 'warning' | 'error';
}

export interface StartReviewRequest {
  pr_url?: string;
  bitbucket_workspace?: string;
  bitbucket_repo_slug?: string;
  pr_number?: number;
  jira_key_override?: string;
}

export interface PagedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface PendingPrItem {
  pr_number: number;
  pr_title: string;
  pr_url: string;
  pr_author?: string;
  pr_author_email?: string;
  source_branch?: string;
  target_branch?: string;
  jira_key?: string;
  jira_url?: string;
  jira_status?: string;
  workspace: string;
  repo_slug: string;
  created_on?: string;
  updated_on?: string;
  existing_review_id?: string;
  existing_review_status?: string;
  approvers?: string[];
  changes_requested_by?: string[];
  comment_count?: number;
  current_user_approved?: boolean;
}

export interface PendingPrsResponse {
  items: PendingPrItem[];
  total: number;
}

