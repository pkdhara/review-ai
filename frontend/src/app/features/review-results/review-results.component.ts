import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { ReviewSignalStore } from '../../core/store/review.store';
import { Finding } from '../../core/models/models';

const CATEGORY_TABS = [
  { key: null, label: 'All', icon: '🔍' },
  { key: 'requirement', label: 'Requirements', icon: '📋' },
  { key: 'code_quality', label: 'Code Quality', icon: '🏗️' },
  { key: 'sql_performance', label: 'SQL', icon: '⚡' },
  { key: 'security', label: 'Security', icon: '🔒' },
  { key: 'refactoring', label: 'Refactoring', icon: '♻️' },
  { key: 'test_coverage', label: 'Tests', icon: '🧪' },
];

@Component({
  selector: 'app-review-results',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="results-page">
      <header class="page-header fade-in">
        <a [routerLink]="['/dashboard']" class="back-link">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="15 18 9 12 15 6"/>
          </svg>
          Dashboard
        </a>
        <div class="header-row">
          <div>
            <h1>Review Results</h1>
            @if (store.currentReview(); as r) {
              <div class="pr-meta-header" style="margin-top:6px; display:flex; align-items:center; gap:10px; flex-wrap:wrap">
                <span class="pr-title-text">{{ r.pr_title || 'PR #' + r.pr_number }}</span>
                @if (r.pr_author || r.author) {
                  <span class="author-chip">
                    👤 {{ r.pr_author || r.author }}
                  </span>
                }
                @if (r.jira_key) {
                  <a [href]="r.jira_url || ('https://freshconcepts.atlassian.net/browse/' + r.jira_key)" target="_blank" rel="noopener" class="jira-tag-link">
                    🔗 {{ r.jira_key }}
                  </a>
                }
                @if (getBitbucketPrUrl(r)) {
                  <a
                    [href]="getBitbucketPrUrl(r)"
                    target="_blank"
                    rel="noopener"
                    class="pr-external-link"
                    [title]="'Open Bitbucket Pull Request: ' + getBitbucketPrUrl(r)"
                  ><svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor" style="flex-shrink:0"><path d="M1.5 2.25A.75.75 0 0 0 .75 3v.75l2.25 16.5a.75.75 0 0 0 .742.649h16.516a.75.75 0 0 0 .742-.649L23.25 3.75V3a.75.75 0 0 0-.75-.75H1.5zM14.5 15h-5L8 9h8l-1.5 6z"/></svg><span>Bitbucket PR #{{ r.pr_number }} ↗</span></a>
                }
              </div>
            }
          </div>
          <a [routerLink]="['/reviews', reviewId, 'approval']" class="btn btn-primary">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
              <polyline points="20 6 9 17 4 12"/>
            </svg>
            Approve & Publish
          </a>
        </div>
      </header>

      <!-- Summary Stats -->
      @if (store.summary(); as summary) {
        <div class="summary-bar fade-in">
          <div class="risk-display" [class]="'risk-' + getRiskLevel(summary.risk_score)">
            <div class="risk-label">Risk Score</div>
            <div class="risk-value">{{ summary.risk_score | number:'1.0-0' }}</div>
            <div class="risk-max">/100</div>
          </div>

          <div class="summary-stats">
            <div class="stat-card stat-primary">
              <div class="stat-value">{{ summary.total_findings }}</div>
              <div class="stat-label">Total Findings</div>
            </div>
            <div class="stat-card stat-critical">
              <div class="stat-value">{{ summary.findings_by_severity['critical'] || 0 }}</div>
              <div class="stat-label">Critical</div>
            </div>
            <div class="stat-card stat-high">
              <div class="stat-value">{{ summary.findings_by_severity['high'] || 0 }}</div>
              <div class="stat-label">High</div>
            </div>
            <div class="stat-card stat-medium">
              <div class="stat-value">{{ summary.findings_by_severity['medium'] || 0 }}</div>
              <div class="stat-label">Medium</div>
            </div>
            <div class="stat-card stat-low">
              <div class="stat-value">{{ summary.findings_by_severity['low'] || 0 }}</div>
              <div class="stat-label">Low</div>
            </div>
          </div>

          <div class="recommendation-badge" [class]="'rec-' + (summary.overall_recommendation || 'NEEDS_DISCUSSION').toLowerCase().replace('_','-')">
            <div class="rec-icon">
              @if (summary.overall_recommendation === 'APPROVE') { ✅ }
              @else if (summary.overall_recommendation === 'REQUEST_CHANGES') { ❌ }
              @else { 💬 }
            </div>
            <div>
              <div class="rec-label">Recommendation</div>
              <div class="rec-value">{{ formatRecommendation(summary.overall_recommendation) }}</div>
            </div>
          </div>
        </div>

        @if (summary.summary_text) {
          <div class="card summary-text-card fade-in">
            <div class="card-header">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/>
              </svg>
              <h4>Executive Summary</h4>
            </div>
            <div class="card-body">
              <p class="summary-text">{{ summary.summary_text }}</p>
            </div>
          </div>
        }
      }

      <!-- Category Tabs -->
      <div class="tab-bar fade-in" style="margin-bottom:20px">
        @for (tab of categoryTabs; track tab.key) {
          <button
            class="tab-item"
            [class.active]="activeCategory() === tab.key"
            (click)="setCategory(tab.key)"
          >
            {{ tab.icon }} {{ tab.label }}
            <span class="count">{{ getTabCount(tab.key) }}</span>
          </button>
        }
      </div>

      <!-- Severity Filter + Search -->
      <div class="filter-row fade-in">
        <input
          class="input"
          style="max-width:320px"
          type="text"
          [(ngModel)]="searchQuery"
          placeholder="Search findings..."
          id="findings-search"
        />
        <div class="severity-filters">
          @for (sev of severities; track sev) {
            <button
              class="sev-btn"
              [class.active]="activeSeverity() === sev.key"
              [class]="'sev-' + sev.key"
              (click)="setSeverity(sev.key)"
            >
              {{ sev.label }}
            </button>
          }
        </div>
      </div>

      <!-- Findings List -->
      <div class="findings-container">
        @if (displayedFindings().length === 0) {
          <div class="card">
            <div class="card-body" style="text-align:center; padding:48px">
              <div style="font-size:2.5rem; margin-bottom:12px">🎉</div>
              <h3>No findings</h3>
              <p class="text-secondary" style="margin-top:6px">No issues match the current filters.</p>
            </div>
          </div>
        }

        @for (finding of displayedFindings(); track finding.id) {
          <div class="card finding-card fade-in" [class]="'finding-' + finding.severity">
            <div class="finding-header">
              <div class="finding-meta">
                <span class="badge" [class]="'badge-' + finding.severity">{{ finding.severity }}</span>
                <span class="category-chip">{{ getCategoryLabel(finding.category) }}</span>
                @if (finding.file_path) {
                  <span class="file-chip">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/>
                      <polyline points="14 2 14 8 20 8"/>
                    </svg>
                    {{ getFileName(finding.file_path) }}{{ finding.line_number ? ':' + finding.line_number : '' }}
                  </span>
                }
              </div>
              <span class="agent-name text-muted">{{ finding.agent_name }}</span>
            </div>

            <div class="finding-body">
              <h4 class="finding-title">{{ finding.title }}</h4>
              <p class="finding-desc">{{ finding.description }}</p>

              @if (finding.evidence) {
                <div class="evidence-block">
                  <div class="evidence-label">Evidence</div>
                  <pre class="evidence-code">{{ finding.evidence }}</pre>
                </div>
              }

              <div class="recommendation-block">
                <div class="rec-label-sm">Recommendation</div>
                <p>{{ finding.recommendation }}</p>
              </div>
            </div>
          </div>
        }
      </div>
    </div>
  `,
  styles: [`
    .results-page { padding: 32px; max-width: 1400px; margin: 0 auto; }
    .page-header { margin-bottom: 24px; }
    .back-link {
      display: inline-flex; align-items: center; gap: 6px;
      color: var(--color-text-muted); font-size: 0.8rem; text-decoration: none;
      margin-bottom: 12px;
      &:hover { color: var(--color-text-primary); }
    }
    .header-row { display: flex; justify-content: space-between; align-items: flex-start; }

    .pr-title-text { color: var(--color-text-secondary); font-size: 0.95rem; font-weight: 500; }

    .author-chip {
      background: rgba(99,102,241,0.12); color: var(--color-primary-light);
      border: 1px solid rgba(99,102,241,0.25); border-radius: 6px;
      padding: 2px 10px; font-size: 0.75rem; font-weight: 600;
      display: inline-flex; align-items: center; gap: 4px;
    }

    .jira-tag-link {
      background: rgba(6,182,212,0.12); color: var(--color-secondary);
      border: 1px solid rgba(6,182,212,0.3); border-radius: 6px;
      padding: 2px 10px; font-size: 0.75rem; font-weight: 700;
      text-decoration: none; transition: all var(--transition-fast);
      display: inline-flex; align-items: center; gap: 4px;
      &:hover {
        background: rgba(6,182,212,0.25);
        color: #67e8f9;
        box-shadow: 0 0 10px rgba(6,182,212,0.25);
      }
    }

    .pr-external-link {
      background: rgba(38, 132, 255, 0.12);
      color: #60a5fa;
      border: 1px solid rgba(38, 132, 255, 0.3);
      border-radius: 6px;
      padding: 3px 12px;
      font-size: 0.78rem;
      font-weight: 700;
      text-decoration: none;
      transition: all var(--transition-fast);
      display: inline-flex;
      align-items: center;
      gap: 6px;

      .url-text {
        font-weight: 500;
        opacity: 0.85;
        font-family: 'JetBrains Mono', monospace;
        font-size: 0.72rem;
      }

      &:hover {
        background: rgba(38, 132, 255, 0.25);
        color: #93c5fd;
        box-shadow: 0 0 12px rgba(38, 132, 255, 0.3);
        transform: translateY(-1px);
      }
    }

    .summary-bar {
      display: flex; align-items: center; gap: 20px; margin-bottom: 20px;
      padding: 24px; background: rgba(15,20,32,0.75);
      border: 1px solid var(--color-border); border-radius: var(--radius-lg);
      backdrop-filter: blur(20px);
      overflow-x: auto;
    }

    .risk-display {
      display: flex; flex-direction: column; align-items: center;
      min-width: 100px; padding: 16px;
      border-radius: var(--radius-md); border: 2px solid;

      &.risk-low    { border-color: var(--color-low);      .risk-value { color: var(--color-low); } }
      &.risk-medium { border-color: var(--color-medium);   .risk-value { color: var(--color-medium); } }
      &.risk-high   { border-color: var(--color-high);     .risk-value { color: var(--color-high); } }
      &.risk-critical { border-color: var(--color-critical); .risk-value { color: var(--color-critical); } }
    }

    .risk-label { font-size: 0.65rem; text-transform: uppercase; letter-spacing: 0.08em; color: var(--color-text-muted); }
    .risk-value { font-size: 2.5rem; font-weight: 900; letter-spacing: -0.04em; }
    .risk-max { font-size: 0.7rem; color: var(--color-text-muted); }

    .summary-stats { display: flex; gap: 12px; flex: 1; }
    .stat-card {
      flex: 1; background: var(--color-surface-2); border: 1px solid var(--color-border);
      border-radius: var(--radius-md); padding: 16px;
      &.stat-primary .stat-value { color: var(--color-primary-light); }
      &.stat-critical .stat-value { color: var(--color-critical); }
      &.stat-high .stat-value { color: var(--color-high); }
      &.stat-medium .stat-value { color: var(--color-medium); }
      &.stat-low .stat-value { color: var(--color-low); }
    }
    .stat-value { font-size: 1.8rem; font-weight: 800; }
    .stat-label { font-size: 0.65rem; color: var(--color-text-muted); text-transform: uppercase; letter-spacing: 0.06em; margin-top: 2px; }

    .recommendation-badge {
      display: flex; align-items: center; gap: 12px;
      padding: 16px 20px; border-radius: var(--radius-md); border: 1px solid;
      min-width: 180px;
      &.rec-approve { background: rgba(34,197,94,0.08); border-color: rgba(34,197,94,0.25); }
      &.rec-request-changes { background: rgba(239,68,68,0.08); border-color: rgba(239,68,68,0.25); }
      &.rec-needs-discussion { background: rgba(99,102,241,0.08); border-color: rgba(99,102,241,0.25); }
    }
    .rec-icon { font-size: 1.5rem; }
    .rec-label { font-size: 0.65rem; color: var(--color-text-muted); text-transform: uppercase; letter-spacing: 0.06em; }
    .rec-value { font-size: 0.9rem; font-weight: 700; margin-top: 2px; }

    .summary-text-card { margin-bottom: 20px; }
    .summary-text { font-size: 0.9rem; line-height: 1.7; white-space: pre-line; }

    .filter-row { display: flex; align-items: center; gap: 16px; margin-bottom: 20px; flex-wrap: wrap; }

    .severity-filters { display: flex; gap: 6px; }
    .sev-btn {
      padding: 6px 14px; border-radius: 100px; font-size: 0.75rem; font-weight: 700;
      cursor: pointer; border: 1px solid; background: transparent; text-transform: uppercase;
      letter-spacing: 0.05em; transition: all var(--transition-fast);
      &.sev-all { color: var(--color-text-muted); border-color: var(--color-border); &.active, &:hover { background: rgba(255,255,255,0.08); color: white; } }
      &.sev-critical { color: #fca5a5; border-color: rgba(239,68,68,0.3); &.active { background: rgba(239,68,68,0.15); } }
      &.sev-high { color: #fdba74; border-color: rgba(249,115,22,0.3); &.active { background: rgba(249,115,22,0.15); } }
      &.sev-medium { color: #fde047; border-color: rgba(234,179,8,0.3); &.active { background: rgba(234,179,8,0.15); } }
      &.sev-low { color: #86efac; border-color: rgba(34,197,94,0.3); &.active { background: rgba(34,197,94,0.15); } }
    }

    .findings-container { display: flex; flex-direction: column; gap: 16px; }

    .finding-card {
      border-left: 3px solid transparent;
      &.finding-critical { border-left-color: var(--color-critical); }
      &.finding-high { border-left-color: var(--color-high); }
      &.finding-medium { border-left-color: var(--color-medium); }
      &.finding-low { border-left-color: var(--color-low); }
    }

    .finding-header {
      display: flex; justify-content: space-between; align-items: center;
      padding: 16px 24px; border-bottom: 1px solid var(--color-border);
    }

    .finding-meta { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }

    .category-chip {
      background: rgba(99,102,241,0.10); color: var(--color-primary-light);
      padding: 2px 10px; border-radius: 4px; font-size: 0.7rem; font-weight: 600;
    }

    .file-chip {
      display: flex; align-items: center; gap: 4px;
      background: var(--color-surface-3); color: var(--color-text-muted);
      padding: 2px 10px; border-radius: 4px; font-size: 0.7rem; font-family: 'JetBrains Mono', monospace;
    }

    .agent-name { font-size: 0.72rem; }

    .finding-body { padding: 20px 24px; display: flex; flex-direction: column; gap: 12px; }

    .finding-title { font-size: 1rem; font-weight: 700; }
    .finding-desc { font-size: 0.875rem; line-height: 1.6; }

    .evidence-block {
      background: var(--color-surface-2); border: 1px solid var(--color-border);
      border-radius: var(--radius-md); padding: 12px 16px;
    }
    .evidence-label, .rec-label-sm {
      font-size: 0.65rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em;
      color: var(--color-text-muted); margin-bottom: 6px;
    }
    .evidence-code {
      font-family: 'JetBrains Mono', monospace; font-size: 0.78rem;
      white-space: pre-wrap; word-break: break-all;
      color: var(--color-text-secondary); margin: 0;
    }

    .recommendation-block {
      background: rgba(34,197,94,0.05); border: 1px solid rgba(34,197,94,0.15);
      border-radius: var(--radius-md); padding: 12px 16px;
      p { font-size: 0.875rem; margin: 0; }
    }
  `]
})
export class ReviewResultsComponent implements OnInit {
  readonly store = inject(ReviewSignalStore);
  private readonly route = inject(ActivatedRoute);

  reviewId = '';
  categoryTabs = CATEGORY_TABS;
  activeCategory = signal<string | null>(null);
  activeSeverity = signal<string | null>(null);
  searchQuery = '';

  severities = [
    { key: null, label: 'All' },
    { key: 'critical', label: 'Critical' },
    { key: 'high', label: 'High' },
    { key: 'medium', label: 'Medium' },
    { key: 'low', label: 'Low' },
  ];

  displayedFindings = computed(() => {
    let items = this.store.findings();
    if (this.activeCategory()) items = items.filter((f) => f.category === this.activeCategory());
    if (this.activeSeverity()) items = items.filter((f) => f.severity === this.activeSeverity());
    if (this.searchQuery) {
      const q = this.searchQuery.toLowerCase();
      items = items.filter(
        (f) =>
          f.title.toLowerCase().includes(q) ||
          f.description.toLowerCase().includes(q) ||
          f.file_path?.toLowerCase().includes(q)
      );
    }
    return items;
  });

  ngOnInit() {
    this.reviewId = this.route.snapshot.paramMap.get('id') || '';
    this.store.loadReview(this.reviewId);
    this.store.loadFindings(this.reviewId);
    this.store.loadSummary(this.reviewId);
  }

  setCategory(cat: string | null) { this.activeCategory.set(cat); }
  setSeverity(sev: string | null) { this.activeSeverity.set(sev); }

  getTabCount(key: string | null): number {
    if (!key) return this.store.findings().length;
    return this.store.findings().filter((f) => f.category === key).length;
  }

  getRiskLevel(score?: number): string {
    if (!score) return 'low';
    if (score >= 70) return 'critical';
    if (score >= 40) return 'high';
    if (score >= 20) return 'medium';
    return 'low';
  }

  getCategoryLabel(cat: string): string {
    return CATEGORY_TABS.find((t) => t.key === cat)?.label || cat;
  }

  getFileName(path: string): string {
    return path.split('/').pop() || path;
  }

  getBitbucketPrUrl(r: any): string {
    if (r?.pr_url) return r.pr_url;
    const ws = r?.workspace || r?.bitbucket_workspace || 'freshconcepts';
    const repo = r?.repo_slug || r?.bitbucket_repo_slug || 'fc-angular';
    if (r?.pr_number) {
      return `https://bitbucket.org/${ws}/${repo}/pull-requests/${r.pr_number}`;
    }
    return '';
  }

  formatRecommendation(rec?: string): string {
    return (rec || 'NEEDS_DISCUSSION').replace(/_/g, ' ');
  }
}
