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
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { firstValueFrom } from 'rxjs';
import { ReviewSignalStore } from '../../core/store/review.store';
import { ReviewApiService } from '../../core/services/review-api.service';
import { Finding } from '../../core/models/models';

const CATEGORY_TABS = [
  { key: null, label: 'All', icon: '🔍' },
  { key: 'pr_defects', label: 'PR Defects', icon: '🚨' },
  { key: 'recommendations', label: 'Recommendations', icon: '💡' },
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
          <div class="header-actions" style="display: flex; gap: 10px; align-items: center;">
            <button
              class="btn btn-primary"
              [disabled]="isRerunning() || !store.currentReview()"
              (click)="rerunReview()"
              id="rerun-review-btn"
              title="Run a new AI review for this pull request"
            >
              <span *ngIf="isRerunning()" class="spin-icon spinning">⚡</span>
              <span *ngIf="!isRerunning()" style="display: flex; align-items: center; gap: 6px;">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                  <path d="M21.5 2v6h-6M2.5 22v-6h6"/>
                  <path d="M2 11.5a10 10 0 0 1 18.8-4.3L21.5 8M22 12.5a10 10 0 0 1-18.8 4.3L2.5 16"/>
                </svg>
                Re-run Review
              </span>
            </button>
          </div>
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

      <!-- Single Unified Filter Tab Bar -->
      <div class="tab-bar fade-in" style="margin-bottom:20px">
        @for (tab of categoryTabs; track tab.key; let idx = $index) {
          @if (idx === 3) {
            <div class="tab-divider"></div>
          }
          <button
            class="tab-item"
            [class.active]="activeCategory() === tab.key"
            [class.tab-pr-defects]="tab.key === 'pr_defects'"
            [class.tab-recommendations]="tab.key === 'recommendations'"
            (click)="setCategory(tab.key)"
          >
            {{ tab.icon }} {{ tab.label }}
            <span class="count">{{ getTabCount(tab.key) }}</span>
          </button>
        }
      </div>

      <!-- Severity Filter + Search -->
      <div class="filter-row fade-in">
        <div class="search-box">
          <svg class="search-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
            <circle cx="11" cy="11" r="8"/>
            <path d="M21 21l-4.35-4.35"/>
          </svg>
          <input
            class="input search-input"
            type="text"
            [(ngModel)]="searchQuery"
            placeholder="Search findings by keyword or file..."
            id="findings-search"
          />
        </div>
        <div class="severity-filters">
          @for (sev of severities; track sev) {
            <button
              class="sev-btn"
              [class.active]="activeSeverity() === sev.key"
              [class]="'sev-' + (sev.key || 'all')"
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
              <h3>No items found</h3>
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
                @if (finding.origin) {
                  <span class="origin-chip" [class]="'origin-' + finding.origin">
                    <span class="chip-icon">{{ getOriginIcon(finding.origin) }}</span>
                    <span>{{ formatOrigin(finding.origin) }}</span>
                  </span>
                }
                @if (finding.change_scope) {
                  <span class="scope-chip" [class]="'scope-' + finding.change_scope">
                    <span class="chip-icon">{{ getScopeIcon(finding.change_scope) }}</span>
                    <span>{{ formatScope(finding.change_scope) }}</span>
                  </span>
                }
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

              <!-- Per-finding PR Comment Section -->
              <div class="pr-comment-block">
                <div class="pr-comment-header">
                  <span class="pr-comment-label">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/>
                    </svg>
                    PR COMMENT
                  </span>
                  <button
                    class="copy-pr-btn"
                    [class.copied]="isFindingCopied(finding.id)"
                    (click)="copyFindingPrComment(finding, $event)"
                    [id]="'copy-pr-btn-' + finding.id"
                    title="Copy PR comment to clipboard"
                  >
                    @if (isFindingCopied(finding.id)) {
                      <span>✅ Copied!</span>
                    } @else {
                      <span style="display:inline-flex;align-items:center;gap:4px">
                        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                          <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>
                          <path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/>
                        </svg>
                        Copy
                      </span>
                    }
                  </button>
                </div>
                <div class="pr-comment-text">
                  {{ finding.pr_comment || 'PR comment unavailable' }}
                </div>
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

    @keyframes spin { to { transform: rotate(360deg); } }
    .spinning { display: inline-block; animation: spin 0.8s linear infinite; }

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

    .class-tab-bar {
      display: inline-flex; align-items: center; gap: 6px;
      padding: 5px; background: rgba(15, 23, 42, 0.75);
      border: 1px solid var(--color-border); border-radius: 12px;
      backdrop-filter: blur(16px); margin-bottom: 20px;
    }

    .btn-class-tab {
      display: inline-flex; align-items: center; gap: 8px;
      padding: 8px 16px; border-radius: 8px; font-size: 0.82rem; font-weight: 600;
      color: var(--color-text-muted); background: transparent; border: 1px solid transparent;
      cursor: pointer; transition: all var(--transition-fast);

      &:hover { color: var(--color-text-primary); background: rgba(255, 255, 255, 0.04); }

      &.active {
        background: var(--color-surface-3); color: #ffffff;
        border-color: rgba(255, 255, 255, 0.12); box-shadow: 0 2px 8px rgba(0, 0, 0, 0.25);
      }

      &.pr-defect-btn.active {
        background: rgba(239, 68, 68, 0.15); color: #fca5a5;
        border-color: rgba(239, 68, 68, 0.35);
      }

      &.rec-btn.active {
        background: rgba(99, 102, 241, 0.15); color: #c7d2fe;
        border-color: rgba(99, 102, 241, 0.35);
      }
    }

    .tab-count-badge {
      display: inline-flex; align-items: center; justify-content: center;
      padding: 1px 7px; border-radius: 100px; font-size: 0.7rem; font-weight: 700;
      background: rgba(255, 255, 255, 0.1); color: var(--color-text-muted);

      &.defect-badge { background: rgba(239, 68, 68, 0.2); color: #fca5a5; }
      &.rec-badge { background: rgba(99, 102, 241, 0.2); color: #a5b4fc; }
    }

    .filter-row { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 24px; flex-wrap: wrap; }

    .search-box {
      position: relative;
      flex: 1;
      min-width: 260px;
      max-width: 420px;

      .search-icon {
        position: absolute;
        left: 14px;
        top: 50%;
        transform: translateY(-50%);
        color: var(--color-text-muted);
        pointer-events: none;
      }

      .search-input {
        padding-left: 38px;
        height: 38px;
        font-size: 0.85rem;
        background: rgba(15, 20, 32, 0.75);
        border-color: var(--color-border);
        border-radius: var(--radius-md);
      }
    }

    .severity-filters { display: flex; gap: 6px; align-items: center; }
    .sev-btn {
      height: 34px;
      padding: 0 14px;
      border-radius: 100px;
      font-size: 0.75rem;
      font-weight: 700;
      cursor: pointer;
      border: 1px solid;
      background: transparent;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      transition: all var(--transition-fast);
      white-space: nowrap;

      &.sev-all {
        color: var(--color-text-secondary);
        border-color: var(--color-border);
        &.active, &:hover { background: rgba(255,255,255,0.08); color: white; border-color: rgba(255,255,255,0.2); }
      }
      &.sev-critical { color: #fca5a5; border-color: rgba(239,68,68,0.3); &.active, &:hover { background: rgba(239,68,68,0.18); border-color: rgba(239,68,68,0.5); } }
      &.sev-high { color: #fdba74; border-color: rgba(249,115,22,0.3); &.active, &:hover { background: rgba(249,115,22,0.18); border-color: rgba(249,115,22,0.5); } }
      &.sev-medium { color: #fde047; border-color: rgba(234,179,8,0.3); &.active, &:hover { background: rgba(234,179,8,0.18); border-color: rgba(234,179,8,0.5); } }
      &.sev-low { color: #86efac; border-color: rgba(34,197,94,0.3); &.active, &:hover { background: rgba(34,197,94,0.18); border-color: rgba(34,197,94,0.5); } }
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

    .origin-chip {
      display: inline-flex; align-items: center; gap: 4px;
      padding: 3px 9px; border-radius: 6px; font-size: 0.7rem; font-weight: 700;
      letter-spacing: 0.02em; border: 1px solid;
      
      &.origin-introduced_by_pr { background: rgba(239, 68, 68, 0.15); color: #fca5a5; border-color: rgba(239, 68, 68, 0.35); }
      &.origin-modified_by_pr { background: rgba(245, 158, 11, 0.15); color: #fde047; border-color: rgba(245, 158, 11, 0.35); }
      &.origin-worsened_by_pr { background: rgba(225, 29, 72, 0.15); color: #fda4af; border-color: rgba(225, 29, 72, 0.35); }
      &.origin-pre_existing { background: rgba(148, 163, 184, 0.14); color: #cbd5e1; border-color: rgba(148, 163, 184, 0.3); }
      &.origin-contextual { background: rgba(99, 102, 241, 0.14); color: #a5b4fc; border-color: rgba(99, 102, 241, 0.3); }
    }

    .scope-chip {
      display: inline-flex; align-items: center; gap: 4px;
      padding: 3px 9px; border-radius: 6px; font-size: 0.7rem; font-weight: 600;
      font-family: 'JetBrains Mono', monospace; border: 1px solid;
      
      &.scope-changed { background: rgba(6, 182, 212, 0.14); color: #67e8f9; border-color: rgba(6, 182, 212, 0.35); }
      &.scope-unchanged { background: rgba(100, 116, 139, 0.16); color: #94a3b8; border-color: rgba(100, 116, 139, 0.3); }
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

    .pr-comment-block {
      border-top: 1px solid var(--color-border);
      padding-top: 12px;
      margin-top: 4px;
    }
    .pr-comment-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 8px;
    }
    .pr-comment-label {
      display: inline-flex;
      align-items: center;
      gap: 5px;
      font-size: 0.65rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: #818cf8;
    }
    .pr-comment-text {
      font-size: 0.875rem;
      line-height: 1.6;
      color: var(--color-text-primary);
      background: rgba(99,102,241,0.05);
      border: 1px solid rgba(99,102,241,0.15);
      border-radius: var(--radius-sm);
      padding: 10px 14px;
      white-space: pre-wrap;
      word-break: break-word;
    }
    .copy-pr-btn {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      padding: 3px 10px;
      font-size: 0.72rem;
      font-weight: 600;
      border: 1px solid var(--color-border);
      border-radius: var(--radius-sm);
      background: transparent;
      color: var(--color-text-secondary);
      cursor: pointer;
      transition: all 0.15s;
      &:hover { background: var(--color-surface-2); color: var(--color-text-primary); }
      &.copied {
        background: rgba(34,197,94,0.15) !important;
        border-color: rgba(34,197,94,0.35) !important;
        color: #86efac !important;
      }
    }
  `]
})
export class ReviewResultsComponent implements OnInit {
  readonly store = inject(ReviewSignalStore);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly api = inject(ReviewApiService);

  isRerunning = signal<boolean>(false);
  reviewId = '';
  categoryTabs = CATEGORY_TABS;
  activeClassification = signal<'all' | 'finding' | 'recommendation'>('all');
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

  prDefectsCount = computed(() => {
    return this.store.findings().filter((f) =>
      f.classification === 'finding' ||
      ['introduced_by_pr', 'modified_by_pr', 'worsened_by_pr'].includes(f.origin || '') ||
      f.affected_by_pr === true
    ).length;
  });

  recommendationsCount = computed(() => {
    return this.store.findings().length - this.prDefectsCount();
  });

  displayedFindings = computed(() => {
    let items = this.store.findings();
    const cat = this.activeCategory();
    if (cat === 'pr_defects') {
      items = items.filter((f) =>
        f.classification === 'finding' ||
        ['introduced_by_pr', 'modified_by_pr', 'worsened_by_pr'].includes(f.origin || '') ||
        f.affected_by_pr === true
      );
    } else if (cat === 'recommendations') {
      items = items.filter((f) =>
        f.classification === 'recommendation' ||
        ['pre_existing', 'contextual', 'unknown'].includes(f.origin || '') ||
        f.affected_by_pr === false
      );
    } else if (cat) {
      items = items.filter((f) => f.category === cat);
    }
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
    // Sort sequence by Severity first (Critical -> High -> Medium -> Low), then file_path and line_number
    const SEVERITY_WEIGHTS: Record<string, number> = {
      critical: 4,
      high: 3,
      medium: 2,
      low: 1,
      info: 0,
    };

    return [...items].sort((a, b) => {
      const weightA = SEVERITY_WEIGHTS[a.severity?.toLowerCase() || ''] ?? 0;
      const weightB = SEVERITY_WEIGHTS[b.severity?.toLowerCase() || ''] ?? 0;
      if (weightA !== weightB) {
        return weightB - weightA;
      }
      const fileA = (a.file_path || '').toLowerCase();
      const fileB = (b.file_path || '').toLowerCase();
      if (fileA !== fileB) {
        if (!fileA) return 1;
        if (!fileB) return -1;
        return fileA.localeCompare(fileB);
      }
      return (a.line_number ?? 0) - (b.line_number ?? 0);
    });
  });

  ngOnInit() {
    this.reviewId = this.route.snapshot.paramMap.get('id') || '';
    this.store.loadReview(this.reviewId);
    this.store.loadFindings(this.reviewId);
    this.store.loadSummary(this.reviewId);
  }

  async rerunReview(): Promise<void> {
    const r = this.store.currentReview();
    if (!r) return;

    this.isRerunning.set(true);
    try {
      const workspace = r.workspace || r.bitbucket_workspace || 'freshconcepts';
      const repoSlug = r.repo_slug || r.bitbucket_repo_slug || 'fc-angular';

      const newReview = await firstValueFrom(
        this.api.startReview({
          pr_url: r.pr_url,
          bitbucket_workspace: workspace,
          bitbucket_repo_slug: repoSlug,
          pr_number: r.pr_number,
          jira_key_override: r.jira_key,
        })
      );
      this.router.navigate(['/reviews', newReview.id, 'progress']);
    } catch (err: any) {
      alert(`Failed to rerun review: ${err.message || 'Unknown error'}`);
    } finally {
      this.isRerunning.set(false);
    }
  }

  setCategory(cat: string | null) { this.activeCategory.set(cat); }
  setSeverity(sev: string | null) { this.activeSeverity.set(sev); }

  getTabCount(key: string | null): number {
    if (!key) return this.store.findings().length;
    if (key === 'pr_defects') return this.prDefectsCount();
    if (key === 'recommendations') return this.recommendationsCount();
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

  formatOrigin(orig?: string): string {
    switch (orig) {
      case 'introduced_by_pr': return 'PR Introduced';
      case 'modified_by_pr': return 'PR Modified';
      case 'worsened_by_pr': return 'PR Worsened';
      case 'pre_existing': return 'Pre-existing';
      case 'contextual': return 'Contextual';
      default: return 'Advisory';
    }
  }

  getOriginIcon(orig?: string): string {
    switch (orig) {
      case 'introduced_by_pr': return '🚨';
      case 'modified_by_pr': return '✏️';
      case 'worsened_by_pr': return '⚠️';
      case 'pre_existing': return '🕒';
      case 'contextual': return '🔍';
      default: return '💡';
    }
  }

  getScopeIcon(scope?: string): string {
    switch (scope) {
      case 'changed': return '⚡';
      case 'unchanged': return '📄';
      default: return '🔹';
    }
  }

  formatScope(scope?: string): string {
    switch (scope) {
      case 'changed': return 'Changed Line';
      case 'unchanged': return 'Unchanged Line';
      default: return scope || '';
    }
  }

  // ── Per-finding PR Comment Copy ──────────────────────────────────────────

  readonly copiedFindingIds = signal<Set<string>>(new Set());

  isFindingCopied(id: string): boolean {
    return this.copiedFindingIds().has(id);
  }

  copyFindingPrComment(finding: Finding, event: MouseEvent): void {
    event.stopPropagation();
    const text = (finding.pr_comment || '').trim();
    if (!text) return;

    const done = () => {
      const s = new Set(this.copiedFindingIds());
      s.add(finding.id);
      this.copiedFindingIds.set(s);
      setTimeout(() => {
        const s2 = new Set(this.copiedFindingIds());
        s2.delete(finding.id);
        this.copiedFindingIds.set(s2);
      }, 2500);
    };

    if (navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(text).then(done, () => this._fallbackCopy(text, done));
    } else {
      this._fallbackCopy(text, done);
    }
  }

  private _fallbackCopy(text: string, onSuccess: () => void): void {
    const el = document.createElement('textarea');
    el.value = text;
    el.style.position = 'fixed';
    el.style.opacity = '0';
    document.body.appendChild(el);
    el.select();
    try { document.execCommand('copy'); onSuccess(); } catch (_) {}
    document.body.removeChild(el);
  }
}

