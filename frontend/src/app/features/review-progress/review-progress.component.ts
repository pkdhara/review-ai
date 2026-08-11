import {
  ChangeDetectionStrategy,
  Component,
  OnDestroy,
  OnInit,
  inject,
  signal,
} from '@angular/core';
import { CommonModule, DatePipe } from '@angular/common';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { ReviewSignalStore } from '../../core/store/review.store';
import { ReviewApiService } from '../../core/services/review-api.service';
import { LogEntry, ProgressEvent } from '../../core/models/models';

const AGENT_LABELS: Record<string, string> = {
  pr_fetch: 'Fetching Pull Request',
  jira_fetch: 'Fetching Jira Story',
  requirement_extraction: 'Extracting Requirements',
  requirement_validation: 'Validating Requirements',
  code_quality: 'Reviewing Code Quality',
  sql_performance: 'Analyzing SQL Performance',
  security: 'Security Analysis',
  refactoring: 'Refactoring Review',
  test_coverage: 'Test Coverage Analysis',
  review_summary: 'Generating Summary',
};

const AGENTS_ORDERED = [
  'pr_fetch', 'jira_fetch', 'requirement_extraction', 'requirement_validation',
  'code_quality', 'sql_performance', 'security', 'refactoring',
  'test_coverage', 'review_summary'
];

@Component({
  selector: 'app-review-progress',
  standalone: true,
  imports: [CommonModule, RouterLink, DatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="progress-page">
      <header class="page-header fade-in">
        <div class="header-top">
          <a routerLink="/dashboard" class="back-link">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <polyline points="15 18 9 12 15 6"/>
            </svg>
            Dashboard
          </a>

          @if (store.currentReview()?.status === 'running' || store.currentReview()?.status === 'pending') {
            <button
              class="btn btn-secondary stop-review-btn"
              (click)="stopReview()"
              id="stop-review-progress-btn"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor"/>
              </svg>
              Stop Review
            </button>
          }
        </div>
        <h1>Review in Progress</h1>
        @if (store.currentReview(); as review) {
          <div class="pr-meta-header" style="margin-top:6px; display:flex; align-items:center; gap:10px; flex-wrap:wrap">
            <span class="text-secondary">PR #{{ review.pr_number }} {{ review.pr_title ? '— ' + review.pr_title : '' }}</span>
            @if (review.pr_author || review.author) {
              <span class="author-chip" style="background:rgba(99,102,241,0.12); color:var(--color-primary-light); border:1px solid rgba(99,102,241,0.25); border-radius:6px; padding:2px 10px; font-size:0.75rem; font-weight:600">
                👤 {{ review.pr_author || review.author }}
              </span>
            }
            @if (review.jira_key) {
              <a
                [href]="review.jira_url || ('https://freshconcepts.atlassian.net/browse/' + review.jira_key)"
                target="_blank"
                rel="noopener"
                style="background:rgba(6,182,212,0.12); color:var(--color-secondary); border:1px solid rgba(6,182,212,0.3); border-radius:6px; padding:2px 10px; font-size:0.75rem; font-weight:700; text-decoration:none"
              >
                🔗 {{ review.jira_key }}
              </a>
            }
          </div>
        }
      </header>

      <!-- Overall Progress -->
      <div class="card fade-in progress-card">
        <div class="card-body">
          <div class="progress-header">
            <div class="agent-chip" *ngIf="currentAgentLabel()">
              <div class="dot"></div>
              {{ currentAgentLabel() }}
            </div>
            <span class="progress-pct">{{ store.currentReview()?.progress_percent || 0 }}%</span>
          </div>
          <div class="progress-bar" style="margin-top:12px">
            <div class="progress-fill" [style.width.%]="store.currentReview()?.progress_percent || 0"></div>
          </div>

          <!-- Agent Steps -->
          <div class="agent-steps">
            @for (agentKey of agents; track agentKey; let i = $index) {
              <div class="agent-step" [class.completed]="isAgentDone(agentKey)" [class.active]="isAgentActive(agentKey)">
                <div class="step-icon">
                  @if (isAgentDone(agentKey)) {
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3">
                      <polyline points="20 6 9 17 4 12"/>
                    </svg>
                  } @else if (isAgentActive(agentKey)) {
                    <div class="step-spinner"></div>
                  } @else {
                    <span>{{ i + 1 }}</span>
                  }
                </div>
                <span class="step-label">{{ agentLabels[agentKey] }}</span>
              </div>
            }
          </div>
        </div>
      </div>

      <!-- Execution Logs -->
      <div class="card fade-in logs-card">
        <div class="card-header">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/>
          </svg>
          <h4>Agent Execution Logs</h4>
          <span class="log-count">{{ store.progressLogs().length }} entries</span>
        </div>
        <div class="logs-container" id="logs-container">
          @if (store.progressLogs().length === 0) {
            <div class="log-empty">Waiting for agent output...</div>
          }
          @for (log of store.progressLogs(); track $index) {
            <div class="log-entry slide-in" [class]="'log-' + log.level">
              <span class="log-time">{{ log.timestamp | date:'HH:mm:ss' }}</span>
              <span class="log-agent">[{{ log.agent }}]</span>
              <span class="log-msg">{{ log.message }}</span>
            </div>
          }
        </div>
      </div>

      <!-- Completed action -->
      @if (store.currentReview()?.status === 'completed') {
        <div class="card completed-card fade-in">
          <div class="card-body completed-content">
            <div class="completed-icon">✅</div>
            <h3>Review Complete!</h3>
            <p class="text-secondary">All agents have finished analysis.</p>
            <div class="completed-actions">
              <a [routerLink]="['/reviews', reviewId, 'results']" class="btn btn-primary btn-lg">
                View Results
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                  <polyline points="9 18 15 12 9 6"/>
                </svg>
              </a>
              <a [routerLink]="['/reviews', reviewId, 'approval']" class="btn btn-secondary btn-lg">
                Go to Approval
              </a>
            </div>
          </div>
        </div>
      }

      @if (store.currentReview()?.status === 'failed') {
        <div class="card failed-card fade-in">
          <div class="card-body">
            <div class="failed-icon">❌</div>
            <h3>Review Failed</h3>
            <p class="error-msg">{{ store.currentReview()?.error_message }}</p>
            <a routerLink="/dashboard" class="btn btn-secondary" style="margin-top:16px">Back to Dashboard</a>
          </div>
        </div>
      }

      @if (store.currentReview()?.status === 'cancelled') {
        <div class="card cancelled-card fade-in">
          <div class="card-body">
            <div class="cancelled-icon">⏹️</div>
            <h3>Review Cancelled</h3>
            <p class="text-secondary">The review process was stopped by user request.</p>
            <a routerLink="/dashboard" class="btn btn-secondary" style="margin-top:16px">Back to Dashboard</a>
          </div>
        </div>
      }
    </div>
  `,
  styles: [`
    .progress-page {
      padding: 32px;
      max-width: 900px;
      margin: 0 auto;
    }

    .page-header { margin-bottom: 24px; }

    .back-link {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      color: var(--color-text-muted);
      font-size: 0.8rem;
      text-decoration: none;
      margin-bottom: 12px;
      transition: color var(--transition-fast);
      &:hover { color: var(--color-text-primary); }
    }

    .progress-card { margin-bottom: 20px; }

    .progress-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
    }

    .progress-pct {
      font-size: 1.5rem;
      font-weight: 800;
      color: var(--color-primary-light);
    }

    .agent-steps {
      margin-top: 24px;
      display: grid;
      grid-template-columns: repeat(5, 1fr);
      gap: 12px;
    }

    .agent-step {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 8px;
      opacity: 0.35;
      transition: opacity var(--transition-med);
      text-align: center;

      &.completed {
        opacity: 1;
      }
      &.active {
        opacity: 1;
      }
    }

    .step-icon {
      width: 32px;
      height: 32px;
      border-radius: 50%;
      background: var(--color-surface-3);
      border: 2px solid var(--color-border);
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 0.7rem;
      font-weight: 700;
      color: var(--color-text-muted);
      transition: all var(--transition-med);

      .agent-step.completed & {
        background: rgba(34,197,94,0.18);
        border-color: #22c55e;
        color: #4ade80;
        box-shadow: 0 0 10px rgba(34,197,94,0.25);
      }

      .agent-step.active & {
        background: rgba(99,102,241,0.2);
        border-color: var(--color-primary);
        color: var(--color-primary-light);
        box-shadow: 0 0 12px rgba(99,102,241,0.3);
        animation: pulse-ring 1.8s ease-in-out infinite;
      }
    }

    @keyframes pulse-ring {
      0%, 100% { box-shadow: 0 0 8px rgba(99,102,241,0.3); }
      50% { box-shadow: 0 0 18px rgba(99,102,241,0.55); }
    }

    .step-spinner {
      width: 14px;
      height: 14px;
      border: 2px solid rgba(99,102,241,0.3);
      border-top-color: var(--color-primary-light);
      border-radius: 50%;
      animation: spin 0.8s linear infinite;
    }

    @keyframes spin { to { transform: rotate(360deg); } }

    .step-label {
      font-size: 0.65rem;
      text-align: center;
      line-height: 1.3;
      color: var(--color-text-muted);
      transition: color var(--transition-med);

      .agent-step.completed & {
        color: var(--color-text-primary);
        font-weight: 600;
      }
      .agent-step.active & {
        color: var(--color-primary-light);
        font-weight: 600;
      }
    }

    .logs-card {
      margin-bottom: 20px;
    }

    .card-header {
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 16px 24px;
      border-bottom: 1px solid var(--color-border);
    }

    .log-count {
      margin-left: auto;
      font-size: 0.75rem;
      background: var(--color-surface-3);
      padding: 2px 10px;
      border-radius: 100px;
      color: var(--color-text-muted);
    }

    .logs-container {
      height: 300px;
      overflow-y: auto;
      overflow-x: hidden;
      padding: 12px 0;
      font-family: 'JetBrains Mono', monospace;
      font-size: 0.8rem;
    }

    .log-empty {
      text-align: center;
      padding: 40px;
      color: var(--color-text-muted);
    }

    .log-entry {
      display: flex;
      align-items: flex-start;
      gap: 12px;
      padding: 6px 24px;
      border-bottom: 1px solid rgba(255,255,255,0.03);
      min-width: 0;

      &.log-error { background: rgba(239,68,68,0.04); }
      &.log-warning { background: rgba(234,179,8,0.04); }
    }

    .log-time { color: var(--color-text-muted); flex-shrink: 0; }
    .log-agent { color: var(--color-primary-light); flex-shrink: 0; min-width: 140px; }
    .log-msg {
      color: var(--color-text-secondary);
      flex: 1;
      min-width: 0;
      word-break: break-word;
      .log-error & { color: #fca5a5; }
      .log-warning & { color: #fde047; }
    }

    .header-top {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 8px;
    }

    .stop-review-btn {
      color: #fca5a5;
      border-color: rgba(239,68,68,0.3);
      background: rgba(239,68,68,0.1);
      display: flex;
      align-items: center;
      gap: 6px;
      padding: 6px 14px;
      font-size: 0.8rem;

      &:hover {
        background: rgba(239,68,68,0.2);
        border-color: rgba(239,68,68,0.5);
        color: #f87171;
      }
    }

    .completed-card, .failed-card, .cancelled-card {
      .card-body {
        text-align: center;
        padding: 48px 24px;
      }
    }

    .completed-icon, .failed-icon, .cancelled-icon { font-size: 3rem; margin-bottom: 16px; }

    .completed-actions {
      display: flex;
      justify-content: center;
      gap: 12px;
      margin-top: 24px;
    }

    .error-msg {
      background: rgba(239,68,68,0.08);
      border: 1px solid rgba(239,68,68,0.2);
      border-radius: var(--radius-md);
      padding: 12px 16px;
      margin-top: 12px;
      font-size: 0.85rem;
      color: #fca5a5;
      font-family: 'JetBrains Mono', monospace;
    }
  `]
})
export class ReviewProgressComponent implements OnInit, OnDestroy {
  readonly store = inject(ReviewSignalStore);
  private readonly api = inject(ReviewApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);

  reviewId = '';
  agents = AGENTS_ORDERED;
  agentLabels = AGENT_LABELS;
  private eventSource?: EventSource;
  private pollInterval?: ReturnType<typeof setInterval>;

  currentAgentLabel = signal<string>('');

  ngOnInit() {
    this.reviewId = this.route.snapshot.paramMap.get('id') || '';
    this.store.clearLogs();
    this.store.loadReview(this.reviewId);
    this.connectSSE();
    this.startPolling();
  }

  ngOnDestroy() {
    this.eventSource?.close();
    if (this.pollInterval) clearInterval(this.pollInterval);
  }

  connectSSE() {
    this.eventSource = this.api.streamProgress(this.reviewId);
    this.eventSource.onmessage = (evt) => {
      try {
        const event: ProgressEvent = JSON.parse(evt.data);
        if (event.current_agent) {
          this.currentAgentLabel.set(AGENT_LABELS[event.current_agent] || event.current_agent);
        }
        if (event.log) this.store.appendLog(event.log);
        this.store.updateCurrentReview({
          status: event.status as any,
          current_agent: event.current_agent,
          progress_percent: event.progress_percent,
        });
        if (event.status === 'completed') {
          setTimeout(() => this.router.navigate(['/reviews', this.reviewId, 'results']), 2000);
        }
      } catch {}
    };
  }

  startPolling() {
    this.pollInterval = setInterval(() => {
      this.store.loadReview(this.reviewId);
    }, 5000);
  }

  isAgentDone(agentKey: string): boolean {
    const current = this.store.currentReview()?.current_agent;
    const progress = this.store.currentReview()?.progress_percent || 0;
    const idx = AGENTS_ORDERED.indexOf(agentKey);
    const currentIdx = AGENTS_ORDERED.indexOf(current || '');
    return currentIdx > idx || progress === 100;
  }

  isAgentActive(agentKey: string): boolean {
    return this.store.currentReview()?.current_agent === agentKey;
  }

  async stopReview() {
    if (confirm('Are you sure you want to stop this review process?')) {
      await this.store.cancelReview(this.reviewId);
    }
  }
}
