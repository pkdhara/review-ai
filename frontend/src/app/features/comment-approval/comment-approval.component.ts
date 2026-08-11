import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  inject,
  signal,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { firstValueFrom } from 'rxjs';
import { ReviewSignalStore } from '../../core/store/review.store';
import { ReviewApiService } from '../../core/services/review-api.service';
import { Finding } from '../../core/models/models';

@Component({
  selector: 'app-comment-approval',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="approval-page">
      <header class="page-header fade-in">
        <a [routerLink]="['/reviews', reviewId, 'results']" class="back-link">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="15 18 9 12 15 6"/>
          </svg>
          Results
        </a>
        <div class="header-row">
          <div>
            <h1>Comment Approval</h1>
            <p class="text-secondary" style="margin-top:4px">
              Review, edit, and approve AI-generated comments before publishing to Bitbucket
            </p>
          </div>
          <div class="header-actions">
            <button class="btn btn-secondary" (click)="approveAll()" [disabled]="processing()">
              ✅ Approve All
            </button>
            <button class="btn btn-secondary" (click)="rejectAll()" [disabled]="processing()">
              ❌ Reject All
            </button>
            <button
              class="btn btn-primary"
              (click)="publishApproved()"
              [disabled]="processing() || store.approvedFindings().length === 0"
            >
              @if (processing()) {
                <span class="spinner-sm"></span> Publishing...
              } @else {
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                  <line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/>
                </svg>
                Publish to Bitbucket ({{ store.approvedFindings().length }})
              }
            </button>
          </div>
        </div>
      </header>

      <!-- Status Bar -->
      <div class="status-bar fade-in">
        <div class="status-item">
          <span class="status-count">{{ store.pendingFindings().length }}</span>
          <span class="status-label">Pending Review</span>
        </div>
        <div class="status-item approved">
          <span class="status-count">{{ store.approvedFindings().length }}</span>
          <span class="status-label">Approved</span>
        </div>
        <div class="status-item rejected">
          <span class="status-count">{{ store.rejectedFindings().length }}</span>
          <span class="status-label">Rejected</span>
        </div>
        <div class="status-item published">
          <span class="status-count">{{ publishedCount() }}</span>
          <span class="status-label">Published</span>
        </div>
      </div>

      @if (successMsg()) {
        <div class="success-alert fade-in">✅ {{ successMsg() }}</div>
      }
      @if (errorMsg()) {
        <div class="error-alert fade-in">❌ {{ errorMsg() }}</div>
      }

      <!-- Reviewer Name -->
      <div class="card fade-in" style="margin-bottom:20px">
        <div class="card-body" style="padding:16px 24px">
          <div class="input-group" style="flex-direction:row; align-items:center; gap:12px">
            <label style="white-space:nowrap; text-transform:none; font-size:0.875rem; font-weight:600; color:var(--color-text-secondary)">
              Reviewer Name:
            </label>
            <input class="input" style="max-width:300px" type="text" [(ngModel)]="reviewerName" placeholder="Your name" id="reviewer-name-input"/>
          </div>
        </div>
      </div>

      <!-- Findings -->
      <div class="findings-list">
        @for (finding of store.findings(); track finding.id) {
          <div class="card finding-approval-card fade-in" [class]="'approval-status-' + finding.approval_status">
            <div class="finding-approval-header">
              <div class="finding-left">
                <input
                  type="checkbox"
                  class="finding-checkbox"
                  [checked]="isSelected(finding.id)"
                  (change)="store.toggleFindingSelection(finding.id)"
                />
                <span class="badge" [class]="'badge-' + finding.severity">{{ finding.severity }}</span>
                <span class="finding-title-text">{{ finding.title }}</span>
                @if (finding.file_path) {
                  <span class="file-chip-sm">{{ getFileName(finding.file_path) }}{{ finding.line_number ? ':' + finding.line_number : '' }}</span>
                }
              </div>
              <div class="finding-right">
                <span class="badge" [class]="'badge-' + finding.approval_status">
                  {{ finding.approval_status }}
                </span>
                @if (finding.published) {
                  <span class="published-badge">📤 Published</span>
                }
              </div>
            </div>

            <div class="finding-approval-body">
              <!-- Comment Editor -->
              <div class="comment-section">
                <div class="comment-label">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/>
                  </svg>
                  Review Comment (editable)
                </div>
                <textarea
                  class="comment-textarea"
                  rows="4"
                  [(ngModel)]="editedComments[finding.id]"
                  [placeholder]="finding.review_comment"
                  (blur)="saveEdit(finding)"
                  [id]="'comment-' + finding.id"
                ></textarea>
              </div>

              @if (finding.description) {
                <div class="description-section">
                  <div class="section-label">Finding Details</div>
                  <p>{{ finding.description }}</p>
                </div>
              }

              <!-- Action Buttons -->
              <div class="action-buttons">
                <button
                  class="btn btn-success btn-sm"
                  (click)="approveSingle(finding)"
                  [disabled]="finding.approval_status === 'approved' || processing()"
                >
                  ✅ Approve
                </button>
                <button
                  class="btn btn-danger btn-sm"
                  (click)="rejectSingle(finding)"
                  [disabled]="finding.approval_status === 'rejected' || processing()"
                >
                  ❌ Reject
                </button>
                <button
                  class="btn btn-secondary btn-sm"
                  (click)="saveEdit(finding)"
                  [disabled]="!editedComments[finding.id] || processing()"
                >
                  💾 Save Edit
                </button>
              </div>
            </div>
          </div>
        }
      </div>
    </div>
  `,
  styles: [`
    .approval-page { padding: 32px; max-width: 1200px; margin: 0 auto; }
    .page-header { margin-bottom: 24px; }
    .back-link {
      display: inline-flex; align-items: center; gap: 6px;
      color: var(--color-text-muted); font-size: 0.8rem; text-decoration: none; margin-bottom: 12px;
      &:hover { color: var(--color-text-primary); }
    }
    .header-row { display: flex; justify-content: space-between; align-items: flex-start; }
    .header-actions { display: flex; gap: 10px; flex-wrap: wrap; }

    .status-bar {
      display: flex; gap: 16px; margin-bottom: 20px;
      padding: 20px 24px; background: rgba(15,20,32,0.75);
      border: 1px solid var(--color-border); border-radius: var(--radius-lg);
    }

    .status-item {
      display: flex; flex-direction: column; align-items: center; gap: 4px; flex: 1;
      &.approved .status-count { color: var(--color-low); }
      &.rejected .status-count { color: var(--color-critical); }
      &.published .status-count { color: var(--color-secondary); }
    }
    .status-count { font-size: 2rem; font-weight: 800; color: var(--color-primary-light); }
    .status-label { font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.08em; color: var(--color-text-muted); }

    .success-alert {
      padding: 12px 16px; background: rgba(34,197,94,0.10); border: 1px solid rgba(34,197,94,0.25);
      border-radius: var(--radius-md); font-size: 0.875rem; color: #86efac; margin-bottom: 16px;
    }
    .error-alert {
      padding: 12px 16px; background: rgba(239,68,68,0.10); border: 1px solid rgba(239,68,68,0.25);
      border-radius: var(--radius-md); font-size: 0.875rem; color: #fca5a5; margin-bottom: 16px;
    }

    .findings-list { display: flex; flex-direction: column; gap: 16px; }

    .finding-approval-card {
      border-left: 3px solid var(--color-border);
      transition: all var(--transition-med);

      &.approval-status-approved { border-left-color: var(--color-low); }
      &.approval-status-rejected { border-left-color: var(--color-critical); opacity: 0.6; }
    }

    .finding-approval-header {
      display: flex; justify-content: space-between; align-items: center;
      padding: 14px 20px; border-bottom: 1px solid var(--color-border);
    }
    .finding-left { display: flex; align-items: center; gap: 10px; flex: 1; min-width: 0; }
    .finding-right { display: flex; align-items: center; gap: 10px; flex-shrink: 0; }

    .finding-checkbox {
      width: 16px; height: 16px; cursor: pointer; accent-color: var(--color-primary);
    }

    .finding-title-text {
      font-size: 0.875rem; font-weight: 600; white-space: nowrap;
      overflow: hidden; text-overflow: ellipsis;
    }

    .file-chip-sm {
      background: var(--color-surface-3); color: var(--color-text-muted);
      padding: 1px 8px; border-radius: 4px; font-size: 0.68rem;
      font-family: 'JetBrains Mono', monospace; flex-shrink: 0;
    }

    .published-badge {
      font-size: 0.7rem; background: rgba(6,182,212,0.12); color: var(--color-secondary);
      border: 1px solid rgba(6,182,212,0.25); padding: 2px 10px; border-radius: 4px;
    }

    .finding-approval-body {
      padding: 20px; display: flex; flex-direction: column; gap: 16px;
    }

    .comment-section { display: flex; flex-direction: column; gap: 8px; }
    .comment-label {
      display: flex; align-items: center; gap: 6px;
      font-size: 0.72rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em;
      color: var(--color-text-muted);
    }

    .comment-textarea {
      background: var(--color-surface-2); border: 1px solid var(--color-border);
      border-radius: var(--radius-md); padding: 12px 16px;
      color: var(--color-text-primary); font-family: inherit; font-size: 0.875rem;
      resize: vertical; outline: none; width: 100%;
      transition: border-color var(--transition-fast), box-shadow var(--transition-fast);

      &:focus { border-color: var(--color-primary); box-shadow: 0 0 0 3px rgba(99,102,241,0.15); }
    }

    .description-section { display: flex; flex-direction: column; gap: 4px; }
    .section-label {
      font-size: 0.65rem; font-weight: 700; text-transform: uppercase;
      letter-spacing: 0.08em; color: var(--color-text-muted);
    }

    .action-buttons { display: flex; gap: 8px; flex-wrap: wrap; }

    .spinner-sm {
      width: 14px; height: 14px; border: 2px solid rgba(255,255,255,0.3);
      border-top-color: white; border-radius: 50%; animation: spin 0.8s linear infinite; display: inline-block;
    }
    @keyframes spin { to { transform: rotate(360deg); } }
  `]
})
export class CommentApprovalComponent implements OnInit {
  readonly store = inject(ReviewSignalStore);
  private readonly api = inject(ReviewApiService);
  private readonly route = inject(ActivatedRoute);

  reviewId = '';
  reviewerName = 'Reviewer';
  processing = signal(false);
  successMsg = signal<string | null>(null);
  errorMsg = signal<string | null>(null);
  editedComments: Record<string, string> = {};
  publishedCount = signal(0);

  ngOnInit() {
    this.reviewId = this.route.snapshot.paramMap.get('id') || '';
    this.store.loadFindings(this.reviewId);
    // Pre-populate edited comment fields
    this.store.findings().forEach((f) => {
      this.editedComments[f.id] = f.edited_comment || f.review_comment;
    });
  }

  isSelected(id: string): boolean {
    return this.store.selectedFindingIds().includes(id);
  }

  getFileName(path: string): string {
    return path.split('/').pop() || path;
  }

  async saveEdit(finding: Finding) {
    const edited = this.editedComments[finding.id];
    if (!edited || edited === finding.review_comment) return;
    try {
      const updated = await firstValueFrom(this.api.updateComment(finding.id, edited));
      this.store.updateFinding(updated);
    } catch (e: any) {
      this.errorMsg.set('Failed to save edit.');
    }
  }

  async approveSingle(finding: Finding) {
    await this.saveEdit(finding);
    this.processing.set(true);
    try {
      await firstValueFrom(this.api.approveComments([finding.id], this.reviewerName));
      this.store.updateFinding({ ...finding, approval_status: 'approved' });
      this.successMsg.set('Comment approved.');
      setTimeout(() => this.successMsg.set(null), 3000);
    } catch { this.errorMsg.set('Approval failed.'); }
    finally { this.processing.set(false); }
  }

  async rejectSingle(finding: Finding) {
    this.processing.set(true);
    try {
      await firstValueFrom(this.api.rejectComments([finding.id]));
      this.store.updateFinding({ ...finding, approval_status: 'rejected' });
    } catch { this.errorMsg.set('Rejection failed.'); }
    finally { this.processing.set(false); }
  }

  async approveAll() {
    if (!this.reviewerName) { this.errorMsg.set('Enter reviewer name first.'); return; }
    this.processing.set(true);
    try {
      const ids = this.store.pendingFindings().map((f) => f.id);
      await firstValueFrom(this.api.approveComments(ids, this.reviewerName));
      await this.store.loadFindings(this.reviewId);
      this.successMsg.set(`${ids.length} comments approved.`);
      setTimeout(() => this.successMsg.set(null), 4000);
    } catch { this.errorMsg.set('Batch approval failed.'); }
    finally { this.processing.set(false); }
  }

  async rejectAll() {
    this.processing.set(true);
    try {
      const ids = this.store.pendingFindings().map((f) => f.id);
      await firstValueFrom(this.api.rejectComments(ids));
      await this.store.loadFindings(this.reviewId);
    } catch { this.errorMsg.set('Batch rejection failed.'); }
    finally { this.processing.set(false); }
  }

  async publishApproved() {
    this.processing.set(true);
    this.errorMsg.set(null);
    try {
      const ids = this.store.approvedFindings().filter((f) => !f.published).map((f) => f.id);
      if (!ids.length) { this.errorMsg.set('No approved unpublished comments.'); return; }
      const res = await firstValueFrom(this.api.publishComments(ids));
      this.publishedCount.set(this.publishedCount() + ids.length);
      await this.store.loadFindings(this.reviewId);
      this.successMsg.set(res.message);
      setTimeout(() => this.successMsg.set(null), 5000);
    } catch (e: any) {
      this.errorMsg.set(e?.error?.detail || 'Publish failed. Check Bitbucket credentials.');
    } finally { this.processing.set(false); }
  }
}
