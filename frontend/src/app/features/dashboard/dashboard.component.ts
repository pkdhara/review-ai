import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  inject,
  signal,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router, RouterLink } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { ReviewSignalStore } from '../../core/store/review.store';
import { ReviewApiService } from '../../core/services/review-api.service';
import { Review, StartReviewRequest } from '../../core/models/models';
import { firstValueFrom } from 'rxjs';

@Component({
  selector: 'app-dashboard',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="dashboard-page">
      <!-- Header -->
      <header class="page-header fade-in">
        <div class="header-content">
          <div>
            <h1 class="page-title">
              <span class="title-gradient">PR Review</span> Dashboard
            </h1>
            <p class="page-subtitle text-secondary">
              AI-powered code review against Jira requirements
            </p>
          </div>
          <div class="header-stats">
            <div class="stat-pill">
              <span class="stat-pill-label">Total Reviews</span>
              <span class="stat-pill-value">{{ store.totalReviews() }}</span>
            </div>
          </div>
        </div>
      </header>

      <div class="dashboard-grid">
        <!-- Start Review Card -->
        <div class="card start-review-card fade-in">
          <div class="card-header">
            <div class="card-icon primary">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
              </svg>
            </div>
            <div>
              <h3>Start New Review</h3>
              <p class="text-muted" style="font-size:0.8rem; margin-top:2px">Enter a Bitbucket PR to begin analysis</p>
            </div>
          </div>

          <div class="card-body">
            <!-- PR URL Input -->
            <div class="input-group">
              <label>Pull Request URL</label>
              <input
                class="input"
                type="url"
                [(ngModel)]="prUrl"
                placeholder="https://bitbucket.org/workspace/repo/pull-requests/123"
                (keyup.enter)="startReview()"
                id="pr-url-input"
              />
            </div>

            <div class="divider-row">
              <div class="divider-line"></div>
              <span class="divider-text">or enter manually</span>
              <div class="divider-line"></div>
            </div>

            <div class="manual-inputs">
              <div class="input-group">
                <label>Workspace</label>
                <input class="input" type="text" [(ngModel)]="workspace" placeholder="my-workspace" id="workspace-input"/>
              </div>
              <div class="input-group">
                <label>Repository</label>
                <input class="input" type="text" [(ngModel)]="repoSlug" placeholder="my-repo" id="repo-input"/>
              </div>
              <div class="input-group">
                <label>PR Number</label>
                <input class="input" type="number" [(ngModel)]="prNumber" placeholder="123" id="pr-number-input"/>
              </div>
            </div>

            <div class="input-group" style="margin-top:16px">
              <label>Jira Key Override (optional)</label>
              <input class="input" type="text" [(ngModel)]="jiraKeyOverride" placeholder="POR-192 (auto-detected from branch)" id="jira-key-input"/>
            </div>

            <button
              class="btn btn-primary w-full"
              style="margin-top:24px"
              [disabled]="submitting()"
              (click)="startReview()"
              id="start-review-btn"
            >
              @if (submitting()) {
                <span class="spinner"></span> Starting Review...
              } @else {
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                  <polygon points="5 3 19 12 5 21 5 3"/>
                </svg>
                Start AI Review
              }
            </button>

            @if (errorMsg()) {
              <div class="error-alert fade-in">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/>
                </svg>
                {{ errorMsg() }}
              </div>
            }
          </div>
        </div>

        <!-- Recent Reviews -->
        <div class="card recent-reviews-card fade-in">
          <div class="card-header">
            <div class="card-icon secondary">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                <polyline points="14 2 14 8 20 8"/>
                <line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/>
                <polyline points="10 9 9 9 8 9"/>
              </svg>
            </div>
            <h3>Recent Reviews</h3>
          </div>

          <div class="card-body" style="padding:0">
            @if (store.loading()) {
              <div class="loading-state">
                <div class="spinner-lg"></div>
                <span>Loading reviews...</span>
              </div>
            } @else if (store.reviews().length === 0) {
              <div class="empty-state">
                <div class="empty-icon">🔍</div>
                <p>No reviews yet. Start your first review!</p>
              </div>
            } @else {
              <div class="review-list">
                @for (review of store.reviews(); track review.id) {
                  <div class="review-list-item" [routerLink]="getReviewRoute(review)">
                    <div class="review-item-left">
                      <div class="status-dot" [class]="'status-' + review.status"></div>
                      <div>
                        <div class="review-item-title">{{ review.pr_title || 'PR #' + review.pr_number }}</div>
                        <div class="review-item-meta">
                          @if (review.pr_author || review.author) {
                            <span class="author-tag">👤 {{ review.pr_author || review.author }}</span>
                          }
                          @if (review.jira_key) {
                            <a
                              [href]="review.jira_url || ('https://freshconcepts.atlassian.net/browse/' + review.jira_key)"
                              target="_blank"
                              rel="noopener"
                              class="jira-tag-link"
                              (click)="$event.stopPropagation()"
                            >
                              🔗 {{ review.jira_key }}
                            </a>
                          }
                          <span class="text-muted">{{ review.source_branch || '—' }}</span>
                        </div>
                      </div>
                    </div>
                    <div class="review-item-right">
                      @if (review.risk_score !== null && review.risk_score !== undefined) {
                        <div class="mini-risk" [class]="getRiskClass(review.risk_score)">
                          {{ review.risk_score }}
                        </div>
                      }
                      <span class="status-badge" [class]="'status-badge-' + review.status">
                        {{ review.status }}
                      </span>

                      <div class="item-actions">
                        @if (review.status === 'running' || review.status === 'pending') {
                          <button
                            class="icon-action-btn stop-action"
                            title="Stop Review"
                            (click)="stopReview(review, $event)"
                            id="stop-review-{{ review.id }}"
                          >
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                              <rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor"/>
                            </svg>
                          </button>
                        }
                        <button
                          class="icon-action-btn delete-action"
                          title="Remove from Review List"
                          (click)="deleteReview(review, $event)"
                          id="delete-review-{{ review.id }}"
                        >
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <polyline points="3 6 5 6 21 6"/>
                            <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
                          </svg>
                        </button>
                      </div>
                    </div>
                  </div>
                }
              </div>
            }
          </div>
        </div>
      </div>
    </div>
  `,
  styles: [`
    .dashboard-page {
      padding: 24px 32px;
      max-width: 1400px;
      margin: 0 auto;
      width: 100%;
      box-sizing: border-box;
    }

    .page-header { margin-bottom: 20px; }

    .header-content {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
    }

    .page-title {
      font-size: 1.8rem;
      font-weight: 800;
      margin-bottom: 4px;
    }

    .title-gradient {
      background: linear-gradient(135deg, var(--color-primary-light), var(--color-secondary));
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
    }

    .stat-pill {
      background: var(--color-surface-2);
      border: 1px solid var(--color-border);
      border-radius: var(--radius-md);
      padding: 10px 18px;
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 2px;
    }

    .stat-pill-label { font-size: 0.65rem; color: var(--color-text-muted); text-transform: uppercase; letter-spacing: 0.08em; }
    .stat-pill-value { font-size: 1.35rem; font-weight: 800; color: var(--color-primary-light); }

    .dashboard-grid {
      display: grid;
      grid-template-columns: 380px minmax(0, 1fr);
      gap: 20px;
      align-items: start;
    }

    .recent-reviews-card {
      display: flex;
      flex-direction: column;
      max-height: calc(100vh - 160px);
      overflow: hidden;
    }

    .card-icon {
      width: 36px;
      height: 36px;
      border-radius: var(--radius-md);
      display: flex;
      align-items: center;
      justify-content: center;
      flex-shrink: 0;

      &.primary {
        background: rgba(99,102,241,0.15);
        color: var(--color-primary-light);
        border: 1px solid rgba(99,102,241,0.25);
      }
      &.secondary {
        background: rgba(6,182,212,0.15);
        color: var(--color-secondary);
        border: 1px solid rgba(6,182,212,0.25);
      }
    }

    .divider-row {
      display: flex;
      align-items: center;
      gap: 12px;
      margin: 16px 0;
    }
    .divider-line { flex: 1; height: 1px; background: var(--color-border); }
    .divider-text { font-size: 0.75rem; color: var(--color-text-muted); white-space: nowrap; }

    .manual-inputs {
      display: grid;
      grid-template-columns: 1fr 1fr 90px;
      gap: 10px;
    }

    .error-alert {
      display: flex;
      align-items: center;
      gap: 8px;
      margin-top: 12px;
      padding: 10px 14px;
      background: rgba(239,68,68,0.10);
      border: 1px solid rgba(239,68,68,0.25);
      border-radius: var(--radius-md);
      font-size: 0.85rem;
      color: #fca5a5;
    }

    .spinner {
      width: 16px;
      height: 16px;
      border: 2px solid rgba(255,255,255,0.3);
      border-top-color: white;
      border-radius: 50%;
      animation: spin 0.8s linear infinite;
      display: inline-block;
    }

    @keyframes spin { to { transform: rotate(360deg); } }

    .loading-state {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 12px;
      padding: 40px;
      color: var(--color-text-muted);
    }

    .spinner-lg {
      width: 32px;
      height: 32px;
      border: 3px solid rgba(99,102,241,0.2);
      border-top-color: var(--color-primary);
      border-radius: 50%;
      animation: spin 1s linear infinite;
    }

    .empty-state {
      text-align: center;
      padding: 48px 24px;
      color: var(--color-text-muted);
    }
    .empty-icon { font-size: 2.5rem; margin-bottom: 12px; }

    .review-list {
      display: flex;
      flex-direction: column;
      overflow-y: auto;
      max-height: calc(100vh - 220px);
    }

    .review-list-item {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 12px 18px;
      border-bottom: 1px solid var(--color-border);
      cursor: pointer;
      transition: background var(--transition-fast);
      min-width: 0;
      width: 100%;
      box-sizing: border-box;

      &:last-child { border-bottom: none; }
      &:hover { background: rgba(255,255,255,0.025); }
    }

    .review-item-left {
      display: flex;
      align-items: center;
      gap: 10px;
      flex: 1;
      min-width: 0;
      overflow: hidden;
    }

    .status-dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      flex-shrink: 0;

      &.status-running  { background: var(--color-primary-light); animation: pulse 1.5s infinite; }
      &.status-completed{ background: var(--color-low); }
      &.status-failed   { background: var(--color-critical); }
      &.status-pending  { background: var(--color-text-muted); }
    }

    .review-item-title {
      font-size: 0.85rem;
      font-weight: 600;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .review-item-meta {
      display: flex;
      align-items: center;
      gap: 6px;
      margin-top: 2px;
      min-width: 0;
      overflow: hidden;

      .text-muted {
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        font-size: 0.75rem;
      }
    }

    .author-tag {
      background: rgba(99,102,241,0.12);
      color: var(--color-primary-light);
      border: 1px solid rgba(99,102,241,0.25);
      border-radius: 4px;
      padding: 1px 7px;
      font-size: 0.7rem;
      font-weight: 600;
      white-space: nowrap;
    }

    .jira-tag-link {
      background: rgba(6,182,212,0.12);
      color: var(--color-secondary);
      border: 1px solid rgba(6,182,212,0.25);
      border-radius: 4px;
      padding: 1px 7px;
      font-size: 0.7rem;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-decoration: none;
      white-space: nowrap;
      transition: all var(--transition-fast);

      &:hover {
        background: rgba(6,182,212,0.25);
        color: #67e8f9;
        box-shadow: 0 0 8px rgba(6,182,212,0.3);
      }
    }

    .review-item-right {
      display: flex;
      align-items: center;
      gap: 12px;
      flex-shrink: 0;
    }

    .mini-risk {
      font-size: 0.85rem;
      font-weight: 800;
      padding: 3px 10px;
      border-radius: 100px;

      &.risk-low    { color: var(--color-low);      background: rgba(34,197,94,0.12);  }
      &.risk-medium { color: var(--color-medium);   background: rgba(234,179,8,0.12);  }
      &.risk-high   { color: var(--color-high);     background: rgba(249,115,22,0.12); }
      &.risk-critical{ color: var(--color-critical); background: rgba(239,68,68,0.12); }
    }

    .status-badge {
      font-size: 0.7rem;
      font-weight: 700;
      padding: 3px 10px;
      border-radius: 100px;
      text-transform: capitalize;

      &.status-badge-completed { background: rgba(34,197,94,0.15);  color: #86efac; }
      &.status-badge-running   { background: rgba(99,102,241,0.15); color: #a5b4fc; }
      &.status-badge-pending   { background: rgba(99,102,241,0.10); color: #818cf8; }
      &.status-badge-failed    { background: rgba(239,68,68,0.15);  color: #fca5a5; }
      &.status-badge-cancelled { background: rgba(234,179,8,0.15);  color: #fde047; }
    }

    .item-actions {
      display: flex;
      align-items: center;
      gap: 6px;
      margin-left: 8px;
    }

    .icon-action-btn {
      background: var(--color-surface-3);
      border: 1px solid var(--color-border);
      border-radius: 6px;
      padding: 5px;
      color: var(--color-text-muted);
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      transition: all var(--transition-fast);

      &:hover {
        color: var(--color-text-primary);
        background: rgba(255,255,255,0.08);
      }

      &.stop-action:hover {
        color: #fca5a5;
        background: rgba(239,68,68,0.15);
        border-color: rgba(239,68,68,0.3);
      }

      &.delete-action:hover {
        color: #fca5a5;
        background: rgba(239,68,68,0.15);
        border-color: rgba(239,68,68,0.3);
      }
    }

    @media (max-width: 900px) {
      .dashboard-grid { grid-template-columns: 1fr; }
      .manual-inputs { grid-template-columns: 1fr 1fr; }
    }
  `]
})
export class DashboardComponent implements OnInit {
  readonly store = inject(ReviewSignalStore);
  private readonly api = inject(ReviewApiService);
  private readonly router = inject(Router);

  prUrl = '';
  workspace = '';
  repoSlug = '';
  prNumber: number | null = null;
  jiraKeyOverride = '';
  submitting = signal(false);
  errorMsg = signal<string | null>(null);

  ngOnInit() {
    this.store.loadReviews();
  }

  async startReview() {
    this.errorMsg.set(null);
    const req: StartReviewRequest = {};

    if (this.prUrl.trim()) {
      req.pr_url = this.prUrl.trim();
    } else if (this.workspace && this.repoSlug && this.prNumber) {
      req.bitbucket_workspace = this.workspace;
      req.bitbucket_repo_slug = this.repoSlug;
      req.pr_number = this.prNumber;
    } else {
      this.errorMsg.set('Please enter a PR URL or workspace, repo, and PR number.');
      return;
    }

    if (this.jiraKeyOverride.trim()) {
      req.jira_key_override = this.jiraKeyOverride.trim();
    }

    this.submitting.set(true);
    try {
      const review = await firstValueFrom(this.api.startReview(req));
      await this.router.navigate(['/reviews', review.id, 'progress']);
    } catch (err: any) {
      this.errorMsg.set(err?.error?.detail || 'Failed to start review. Check your settings.');
    } finally {
      this.submitting.set(false);
    }
  }

  async stopReview(review: Review, event: Event) {
    event.stopPropagation();
    if (confirm(`Are you sure you want to stop the review for ${review.pr_title || 'PR #' + review.pr_number}?`)) {
      await this.store.cancelReview(review.id);
    }
  }

  async deleteReview(review: Review, event: Event) {
    event.stopPropagation();
    if (confirm(`Are you sure you want to remove ${review.pr_title || 'PR #' + review.pr_number} from the review list?`)) {
      await this.store.deleteReview(review.id);
    }
  }

  getReviewRoute(review: Review): string[] {
    if (review.status === 'completed') return ['/reviews', review.id, 'results'];
    if (review.status === 'running' || review.status === 'pending') return ['/reviews', review.id, 'progress'];
    return ['/reviews', review.id, 'results'];
  }

  getRiskClass(score: number): string {
    if (score >= 70) return 'risk-critical';
    if (score >= 40) return 'risk-high';
    if (score >= 20) return 'risk-medium';
    return 'risk-low';
  }
}
