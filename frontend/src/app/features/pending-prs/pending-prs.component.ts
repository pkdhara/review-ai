import { Component, OnInit, signal, computed, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { firstValueFrom } from 'rxjs';
import { ReviewApiService } from '../../core/services/review-api.service';
import { PendingPrItem } from '../../core/models/models';

@Component({
  selector: 'app-pending-prs',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <div class="pending-prs-container">
      <!-- Header -->
      <header class="page-header">
        <div class="header-left">
          <div class="header-icon">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="18" cy="18" r="3"/>
              <circle cx="6" cy="6" r="3"/>
              <path d="M13 6h3a2 2 0 0 1 2 2v7"/>
              <line x1="6" y1="9" x2="6" y2="21"/>
            </svg>
          </div>
          <div>
            <h1 class="page-title">
              PR Reviews Pending
              <span class="count-badge" *ngIf="!loading()">{{ filteredPrs().length }}</span>
            </h1>
            <p class="page-subtitle">
              {{ onlyInternalReview() ? 'Pull requests for Jira tasks currently in Internal Review' : 'All open Bitbucket pull requests' }}
            </p>
          </div>
        </div>

        <div class="header-actions">
          <button class="btn btn-secondary" (click)="loadPendingPrs()" [disabled]="loading()">
            <span class="spin-icon" [class.spinning]="loading()">🔄</span>
            Refresh PRs
          </button>
        </div>
      </header>

      <!-- Filter Bar & Toggle -->
      <div class="filter-bar">
        <div class="search-input-wrapper">
          <span class="search-icon">🔍</span>
          <input
            type="text"
            class="form-control search-input"
            placeholder="Search by title, author, or Jira key (e.g. FRES-8729)..."
            [ngModel]="searchQuery()"
            (ngModelChange)="searchQuery.set($event)"
          />
          <button *ngIf="searchQuery()" class="clear-btn" (click)="searchQuery.set('')">✕</button>
        </div>

        <div class="toggle-group">
          <label class="toggle-label">
            <input
              type="checkbox"
              [checked]="onlyInternalReview()"
              (change)="toggleInternalReviewFilter($event)"
            />
            <span class="toggle-text">📌 Internal Review Only</span>
          </label>
        </div>
      </div>

      <!-- Loading State -->
      <div *ngIf="loading()" class="loading-container">
        <div class="spinner"></div>
        <p>Fetching PRs and cross-referencing Jira task status...</p>
      </div>

      <!-- Error Banner -->
      <div *ngIf="error()" class="error-banner">
        ⚠️ {{ error() }}
        <button class="btn btn-sm btn-secondary" (click)="loadPendingPrs()">Retry</button>
      </div>

      <!-- Empty State -->
      <div *ngIf="!loading() && filteredPrs().length === 0" class="empty-state">
        <div class="empty-icon">🎉</div>
        <h3>No Pending PR Reviews</h3>
        <p *ngIf="onlyInternalReview()">
          No open PRs match Jira tasks in "Internal Review". Try unchecking "Internal Review Only" to view all open PRs.
        </p>
        <p *ngIf="!onlyInternalReview()">
          No open Bitbucket pull requests match your search criteria.
        </p>
      </div>

      <!-- PR List Grid -->
      <div *ngIf="!loading() && filteredPrs().length > 0" class="pr-grid">
        <div *ngFor="let item of filteredPrs()" class="pr-card">
          <!-- Card Top: Header & Badges -->
          <div class="pr-card-header">
            <div class="pr-title-group">
              <span class="pr-num-pill">#{{ item.pr_number }}</span>
              <h3 class="pr-title" [title]="item.pr_title">{{ item.pr_title }}</h3>
            </div>
            
            <div class="pr-status-badge" [class]="'status-' + (item.existing_review_status || 'unreviewed')">
              <span class="dot"></span>
              {{ getStatusLabel(item.existing_review_status) }}
            </div>
          </div>

          <!-- Card Body: Meta Badges & Branch Flow -->
          <div class="pr-card-body">
            <div class="meta-row">
              <span *ngIf="item.pr_author" class="author-chip" [title]="'Author: ' + item.pr_author">
                👤 {{ item.pr_author }}
              </span>

              <a
                *ngIf="getBitbucketPrUrl(item)"
                [href]="getBitbucketPrUrl(item)"
                target="_blank"
                rel="noopener"
                class="bitbucket-chip-link"
                [title]="'Open Pull Request #' + item.pr_number + ' in Bitbucket'"
              >
                <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor" style="vertical-align:-1px; margin-right:3px">
                  <path d="M1.5 2.25A.75.75 0 0 0 .75 3v.75l2.25 16.5a.75.75 0 0 0 .742.649h16.516a.75.75 0 0 0 .742-.649L23.25 3.75V3a.75.75 0 0 0-.75-.75H1.5zM14.5 15h-5L8 9h8l-1.5 6z"/>
                </svg>
                PR #{{ item.pr_number }}
              </a>

              <a
                *ngIf="item.jira_key"
                [href]="item.jira_url || ('https://freshconcepts.atlassian.net/browse/' + item.jira_key)"
                target="_blank"
                rel="noopener"
                class="jira-chip-link"
                [title]="'Open Jira ' + item.jira_key"
              >
                🔗 {{ item.jira_key }}
              </a>

              <span *ngIf="item.jira_status" class="jira-status-chip">
                📌 {{ item.jira_status }}
              </span>
            </div>

            <div class="branch-flow">
              <span class="branch source" [title]="item.source_branch">{{ item.source_branch || '—' }}</span>
              <span class="arrow">➔</span>
              <span class="branch target" [title]="item.target_branch">{{ item.target_branch || '—' }}</span>
            </div>
          </div>

          <!-- Card Footer: Repo Info & Clean Button Layout -->
          <div class="pr-card-footer">
            <div class="footer-top-row">
              <span class="repo-info">
                📂 {{ item.workspace }}/{{ item.repo_slug }}
              </span>
              <a
                [href]="item.pr_url"
                target="_blank"
                rel="noopener"
                class="bitbucket-link"
              >
                Bitbucket ↗
              </a>
            </div>

            <div class="action-buttons-row">
              <button
                *ngIf="item.existing_review_id"
                class="btn btn-sm btn-secondary flex-btn"
                (click)="viewReviewResults(item.existing_review_id)"
              >
                👁️ View Results
              </button>

              <button
                class="btn btn-sm btn-primary flex-btn"
                [disabled]="startingPr() === item.pr_number"
                (click)="runReview(item)"
              >
                <span *ngIf="startingPr() === item.pr_number" class="spin-icon spinning">⚡</span>
                <span *ngIf="startingPr() !== item.pr_number">⚡ {{ item.existing_review_id ? 'Re-run Review' : 'Run AI Review' }}</span>
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  `,
  styles: [`
    .pending-prs-container {
      padding: 32px;
      max-width: 1400px;
      margin: 0 auto;
    }

    .page-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 28px;
    }

    .header-left {
      display: flex;
      align-items: center;
      gap: 16px;
    }

    .header-icon {
      width: 48px;
      height: 48px;
      background: linear-gradient(135deg, var(--color-primary), var(--color-secondary));
      border-radius: 12px;
      display: flex;
      align-items: center;
      justify-content: center;
      color: white;
      box-shadow: 0 4px 20px rgba(99,102,241,0.35);
    }

    .page-title {
      font-size: 1.6rem;
      font-weight: 800;
      color: var(--color-text-primary);
      margin: 0 0 4px;
      display: flex;
      align-items: center;
      gap: 12px;
    }

    .count-badge {
      font-size: 0.85rem;
      font-weight: 700;
      background: rgba(99,102,241,0.2);
      color: var(--color-primary-light);
      padding: 2px 10px;
      border-radius: 20px;
      border: 1px solid rgba(99,102,241,0.3);
    }

    .page-subtitle {
      font-size: 0.9rem;
      color: var(--color-text-secondary);
      margin: 0;
    }

    .filter-bar {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 20px;
      margin-bottom: 28px;
      flex-wrap: wrap;
    }

    .search-input-wrapper {
      position: relative;
      flex: 1;
      min-width: 300px;
      max-width: 600px;

      .search-icon {
        position: absolute;
        left: 14px;
        top: 50%;
        transform: translateY(-50%);
        font-size: 0.9rem;
        opacity: 0.6;
      }

      .search-input {
        width: 100%;
        padding: 12px 40px;
        background: rgba(15,20,32,0.7);
        border: 1px solid var(--color-border);
        border-radius: var(--radius-md);
        color: var(--color-text-primary);
        font-size: 0.9rem;

        &:focus {
          outline: none;
          border-color: var(--color-primary);
          box-shadow: 0 0 0 3px rgba(99,102,241,0.15);
        }
      }

      .clear-btn {
        position: absolute;
        right: 12px;
        top: 50%;
        transform: translateY(-50%);
        background: none;
        border: none;
        color: var(--color-text-muted);
        cursor: pointer;
        font-size: 0.9rem;

        &:hover { color: var(--color-text-primary); }
      }
    }

    .toggle-group {
      display: flex;
      align-items: center;
      background: rgba(15,20,32,0.7);
      padding: 10px 18px;
      border-radius: var(--radius-md);
      border: 1px solid var(--color-border);

      .toggle-label {
        display: flex;
        align-items: center;
        gap: 10px;
        cursor: pointer;
        font-size: 0.85rem;
        font-weight: 600;
        color: var(--color-text-primary);
        user-select: none;

        input[type="checkbox"] {
          accent-color: var(--color-primary);
          width: 16px;
          height: 16px;
          cursor: pointer;
        }

        .toggle-text {
          color: #a5b4fc;
        }
      }
    }

    .loading-container {
      text-align: center;
      padding: 64px;
      color: var(--color-text-secondary);

      .spinner {
        width: 40px;
        height: 40px;
        border: 3px solid rgba(99,102,241,0.2);
        border-top-color: var(--color-primary);
        border-radius: 50%;
        animation: spin 0.8s linear infinite;
        margin: 0 auto 16px;
      }
    }

    .spin-icon.spinning {
      display: inline-block;
      animation: spin 0.8s linear infinite;
    }

    @keyframes spin {
      to { transform: rotate(360deg); }
    }

    .error-banner {
      background: rgba(239,68,68,0.1);
      border: 1px solid rgba(239,68,68,0.3);
      color: #fca5a5;
      padding: 16px 20px;
      border-radius: var(--radius-md);
      margin-bottom: 24px;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }

    .empty-state {
      text-align: center;
      padding: 64px 20px;
      background: rgba(15,20,32,0.4);
      border: 1px dashed var(--color-border);
      border-radius: var(--radius-lg);

      .empty-icon { font-size: 3rem; margin-bottom: 16px; }
      h3 { margin: 0 0 8px; color: var(--color-text-primary); }
      p { color: var(--color-text-secondary); margin: 0; max-width: 500px; margin-inline: auto; }
    }

    .pr-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
      gap: 24px;
    }

    .pr-card {
      background: rgba(18, 24, 38, 0.85);
      border: 1px solid rgba(255, 255, 255, 0.08);
      border-radius: 14px;
      padding: 20px;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      transition: all 0.25s ease;
      box-shadow: 0 4px 16px rgba(0, 0, 0, 0.25);

      &:hover {
        border-color: rgba(99, 102, 241, 0.45);
        transform: translateY(-3px);
        box-shadow: 0 10px 30px rgba(0, 0, 0, 0.4), 0 0 15px rgba(99, 102, 241, 0.1);
      }
    }

    .pr-card-header {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 12px;
      margin-bottom: 16px;
    }

    .pr-title-group {
      display: flex;
      align-items: flex-start;
      gap: 8px;
      flex: 1;
      min-width: 0;
    }

    .pr-num-pill {
      font-size: 0.72rem;
      font-weight: 800;
      font-family: var(--font-mono, monospace);
      background: rgba(99, 102, 241, 0.18);
      color: #818cf8;
      padding: 2px 7px;
      border-radius: 6px;
      border: 1px solid rgba(99, 102, 241, 0.3);
      flex-shrink: 0;
      margin-top: 2px;
    }

    .pr-title {
      font-size: 0.92rem;
      font-weight: 700;
      color: #f1f5f9;
      margin: 0;
      line-height: 1.4;
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
      word-break: break-word;
    }

    .pr-status-badge {
      font-size: 0.7rem;
      font-weight: 700;
      padding: 4px 10px;
      border-radius: 20px;
      display: flex;
      align-items: center;
      gap: 6px;
      flex-shrink: 0;

      .dot {
        width: 6px;
        height: 6px;
        border-radius: 50%;
      }

      &.status-unreviewed {
        background: rgba(148,163,184,0.12);
        color: #cbd5e1;
        border: 1px solid rgba(148,163,184,0.25);
        .dot { background: #94a3b8; }
      }

      &.status-completed {
        background: rgba(16,185,129,0.12);
        color: #6ee7b7;
        border: 1px solid rgba(16,185,129,0.25);
        .dot { background: #10b981; }
      }

      &.status-failed {
        background: rgba(239,68,68,0.12);
        color: #fca5a5;
        border: 1px solid rgba(239,68,68,0.25);
        .dot { background: #ef4444; }
      }

      &.status-pending, &.status-running {
        background: rgba(99,102,241,0.15);
        color: var(--color-primary-light);
        border: 1px solid rgba(99,102,241,0.3);
        .dot { background: var(--color-primary); animation: spin 1s infinite; }
      }
    }

    .pr-card-body {
      margin-bottom: 18px;
    }

    .meta-row {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin-bottom: 12px;
    }

    .author-chip {
      font-size: 0.72rem;
      font-weight: 600;
      color: #cbd5e1;
      background: rgba(255,255,255,0.05);
      padding: 3px 9px;
      border-radius: 10px;
      border: 1px solid rgba(255,255,255,0.08);
      white-space: nowrap;
    }

    .bitbucket-chip-link {
      font-size: 0.72rem;
      font-weight: 700;
      color: #60a5fa;
      background: rgba(38, 132, 255, 0.12);
      padding: 3px 9px;
      border-radius: 10px;
      border: 1px solid rgba(38, 132, 255, 0.25);
      text-decoration: none;
      transition: all 0.2s;
      white-space: nowrap;

      &:hover {
        background: rgba(38, 132, 255, 0.22);
        color: #93c5fd;
        transform: translateY(-1px);
      }
    }

    .jira-chip-link {
      font-size: 0.72rem;
      font-weight: 700;
      color: #38bdf8;
      background: rgba(56,189,248,0.12);
      padding: 3px 9px;
      border-radius: 10px;
      border: 1px solid rgba(56,189,248,0.25);
      text-decoration: none;
      transition: all 0.2s;
      white-space: nowrap;

      &:hover {
        background: rgba(56,189,248,0.22);
        color: #7dd3fc;
      }
    }

    .jira-status-chip {
      font-size: 0.72rem;
      font-weight: 700;
      color: #fbbf24;
      background: rgba(245,158,11,0.12);
      padding: 3px 9px;
      border-radius: 10px;
      border: 1px solid rgba(245,158,11,0.25);
      white-space: nowrap;
    }

    .branch-flow {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 0.78rem;
      font-family: var(--font-mono, monospace);
      color: #94a3b8;
      background: rgba(10, 14, 24, 0.6);
      padding: 8px 12px;
      border-radius: 8px;
      border: 1px solid rgba(255, 255, 255, 0.04);

      .branch {
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        flex: 1;
        min-width: 0;

        &.source { color: #cbd5e1; }
        &.target { color: #94a3b8; }
      }

      .arrow { color: #818cf8; opacity: 0.8; flex-shrink: 0; }
    }

    .pr-card-footer {
      display: flex;
      flex-direction: column;
      gap: 12px;
      padding-top: 14px;
      border-top: 1px solid rgba(255, 255, 255, 0.06);
    }

    .footer-top-row {
      display: flex;
      justify-content: space-between;
      align-items: center;
    }

    .repo-info {
      font-size: 0.73rem;
      color: var(--color-text-muted);
      font-weight: 500;
    }

    .bitbucket-link {
      font-size: 0.75rem;
      font-weight: 600;
      color: #94a3b8;
      text-decoration: none;
      transition: color 0.2s;

      &:hover {
        color: #f1f5f9;
        text-decoration: underline;
      }
    }

    .action-buttons-row {
      display: flex;
      gap: 10px;
      width: 100%;
    }

    .flex-btn {
      flex: 1;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      text-align: center;
      gap: 6px;
      white-space: nowrap;
    }

    .btn {
      padding: 9px 16px;
      border-radius: 8px;
      font-weight: 600;
      font-size: 0.82rem;
      cursor: pointer;
      transition: all var(--transition-fast);

      &.btn-sm {
        padding: 8px 12px;
        font-size: 0.8rem;
      }

      &.btn-primary {
        background: linear-gradient(135deg, #6366f1, #4f46e5);
        color: white;
        border: none;
        box-shadow: 0 2px 8px rgba(99, 102, 241, 0.3);

        &:hover:not(:disabled) {
          background: linear-gradient(135deg, #4f46e5, #4338ca);
          box-shadow: 0 4px 14px rgba(99, 102, 241, 0.45);
          transform: translateY(-1px);
        }
      }

      &.btn-secondary {
        background: rgba(255, 255, 255, 0.06);
        color: #e2e8f0;
        border: 1px solid rgba(255, 255, 255, 0.12);

        &:hover:not(:disabled) {
          background: rgba(255, 255, 255, 0.12);
          border-color: rgba(255, 255, 255, 0.2);
        }
      }
    }
  `]
})
export class PendingPrsComponent implements OnInit {
  private readonly api = inject(ReviewApiService);
  private readonly router = inject(Router);

  prs = signal<PendingPrItem[]>([]);
  loading = signal<boolean>(true);
  error = signal<string | null>(null);
  searchQuery = signal<string>('');
  onlyInternalReview = signal<boolean>(true);
  startingPr = signal<number | null>(null);

  filteredPrs = computed(() => {
    const q = this.searchQuery().toLowerCase().trim();
    if (!q) return this.prs();

    return this.prs().filter((item) =>
      item.pr_title.toLowerCase().includes(q) ||
      (item.pr_author && item.pr_author.toLowerCase().includes(q)) ||
      (item.jira_key && item.jira_key.toLowerCase().includes(q)) ||
      (item.jira_status && item.jira_status.toLowerCase().includes(q)) ||
      (item.source_branch && item.source_branch.toLowerCase().includes(q)) ||
      item.pr_number.toString().includes(q)
    );
  });

  ngOnInit(): void {
    this.loadPendingPrs();
  }

  toggleInternalReviewFilter(event: Event): void {
    const checked = (event.target as HTMLInputElement).checked;
    this.onlyInternalReview.set(checked);
    this.loadPendingPrs();
  }

  async loadPendingPrs(): Promise<void> {
    this.loading.set(true);
    this.error.set(null);

    try {
      const res = await firstValueFrom(this.api.getPendingPrs(this.onlyInternalReview()));
      this.prs.set(res.items || []);
    } catch (err: any) {
      this.error.set(err.message || 'Failed to load pending pull requests from Bitbucket.');
    } finally {
      this.loading.set(false);
    }
  }

  getBitbucketPrUrl(item: any): string {
    if (item?.pr_url) return item.pr_url;
    const ws = item?.workspace || item?.bitbucket_workspace || 'freshconcepts';
    const repo = item?.repo_slug || item?.bitbucket_repo_slug || 'fc-angular';
    if (item?.pr_number) {
      return `https://bitbucket.org/${ws}/${repo}/pull-requests/${item.pr_number}`;
    }
    return '';
  }

  getStatusLabel(status?: string): string {
    if (!status) return 'Needs Review';
    if (status === 'completed') return 'Reviewed';
    if (status === 'failed') return 'Review Failed';
    if (status === 'pending' || status === 'running') return 'In Progress';
    return status;
  }

  viewReviewResults(reviewId: string): void {
    this.router.navigate(['/reviews', reviewId, 'results']);
  }

  async runReview(item: PendingPrItem): Promise<void> {
    this.startingPr.set(item.pr_number);

    try {
      const review = await firstValueFrom(
        this.api.startReview({
          pr_url: item.pr_url,
          bitbucket_workspace: item.workspace,
          bitbucket_repo_slug: item.repo_slug,
          pr_number: item.pr_number,
          jira_key_override: item.jira_key,
        })
      );
      this.router.navigate(['/reviews', review.id, 'progress']);
    } catch (err: any) {
      alert(`Failed to start review: ${err.message || 'Unknown error'}`);
    } finally {
      this.startingPr.set(null);
    }
  }
}
