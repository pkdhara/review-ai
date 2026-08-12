import { Injectable, signal, computed, inject, OnDestroy } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { ReviewApiService } from '../services/review-api.service';
import { PendingPrItem } from '../models/models';

import { Router } from '@angular/router';

const ARCHIVED_PRS_STORAGE_KEY = 'reviewai_archived_prs';

@Injectable({ providedIn: 'root' })
export class PendingPrStore implements OnDestroy {
  private readonly api = inject(ReviewApiService);
  private readonly router = inject(Router);
  private timerId: any = null;

  readonly prs = signal<PendingPrItem[]>([]);
  readonly loading = signal<boolean>(false);
  
  readonly myPrs = signal<PendingPrItem[]>([]);
  readonly myPrsLoading = signal<boolean>(false);

  readonly error = signal<string | null>(null);
  readonly onlyInternalReview = signal<boolean>(true);
  readonly showArchived = signal<boolean>(false);
  readonly lastFetchedAt = signal<Date | null>(null);

  // Persistent set of archived PR keys (e.g., workspace/repo/pr_number or pr_url)
  readonly archivedKeys = signal<string[]>(this.loadArchivedKeysFromStorage());

  // Non-archived pending PRs for default display
  readonly unarchivedPrs = computed(() =>
    this.prs().filter((item) => !this.isArchived(item))
  );

  // Archived pending PRs
  readonly archivedPrs = computed(() =>
    this.prs().filter((item) => this.isArchived(item))
  );

  // Active count for sidebar navigation badge (reflects unarchived pending PRs)
  readonly count = computed(() => this.unarchivedPrs().length);
  readonly archivedCount = computed(() => this.archivedPrs().length);

  constructor() {
    this.startAutoRefresh();
  }

  getPrKey(item: PendingPrItem): string {
    if (item.pr_url) return item.pr_url;
    const ws = item.workspace || 'freshconcepts';
    const repo = item.repo_slug || 'fc-angular';
    return `${ws}/${repo}/${item.pr_number}`;
  }

  isArchived(item: PendingPrItem): boolean {
    return this.archivedKeys().includes(this.getPrKey(item));
  }

  archivePr(item: PendingPrItem): void {
    const key = this.getPrKey(item);
    if (!this.archivedKeys().includes(key)) {
      const updated = [...this.archivedKeys(), key];
      this.archivedKeys.set(updated);
      this.saveArchivedKeysToStorage(updated);
    }
  }

  unarchivePr(item: PendingPrItem): void {
    const key = this.getPrKey(item);
    const updated = this.archivedKeys().filter((k) => k !== key);
    this.archivedKeys.set(updated);
    this.saveArchivedKeysToStorage(updated);
  }

  clearAllArchived(): void {
    this.archivedKeys.set([]);
    localStorage.removeItem(ARCHIVED_PRS_STORAGE_KEY);
  }

  toggleShowArchived(): void {
    this.showArchived.set(!this.showArchived());
  }

  startAutoRefresh(): void {
    // Initial fetch on app startup
    this.loadPendingPrs();

    // Auto-fetch pending PRs every 30 minutes (30 * 60 * 1000 = 1,800,000 ms)
    const THIRTY_MINUTES = 30 * 60 * 1000;
    this.timerId = setInterval(() => {
      // Don't refetch if the user is actively viewing the Pending PRs page to avoid UI jumps
      if (this.router.url !== '/pending-prs') {
        this.loadPendingPrs();
      }
    }, THIRTY_MINUTES);
  }

  async loadPendingPrs(onlyInternal: boolean = this.onlyInternalReview()): Promise<void> {
    this.onlyInternalReview.set(onlyInternal);
    this.loading.set(true);
    this.myPrsLoading.set(true);
    this.error.set(null);

    try {
      const [pendingRes, myRes] = await Promise.all([
        firstValueFrom(this.api.getPendingPrs(onlyInternal, false)),
        firstValueFrom(this.api.getPendingPrs(false, true)) // My PRs, don't filter by internal review
      ]);
      this.prs.set(pendingRes.items || []);
      this.myPrs.set(myRes.items || []);
      this.lastFetchedAt.set(new Date());
    } catch (err: any) {
      this.error.set(err.message || 'Failed to load pull requests from Bitbucket.');
    } finally {
      this.loading.set(false);
      this.myPrsLoading.set(false);
    }
  }

  private loadArchivedKeysFromStorage(): string[] {
    try {
      const raw = localStorage.getItem(ARCHIVED_PRS_STORAGE_KEY);
      return raw ? JSON.parse(raw) : [];
    } catch (e) {
      console.error('Failed to parse archived PRs from localStorage', e);
      return [];
    }
  }

  private saveArchivedKeysToStorage(keys: string[]): void {
    try {
      localStorage.setItem(ARCHIVED_PRS_STORAGE_KEY, JSON.stringify(keys));
    } catch (e) {
      console.error('Failed to save archived PRs to localStorage', e);
    }
  }

  ngOnDestroy(): void {
    if (this.timerId) {
      clearInterval(this.timerId);
    }
  }
}
