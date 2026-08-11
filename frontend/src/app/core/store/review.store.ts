import { signalStore, withState, withMethods, withComputed, patchState } from '@ngrx/signals';
import { inject } from '@angular/core';
import { computed } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { Finding, LogEntry, PagedResponse, Review, ReviewSummary } from '../models/models';
import { ReviewApiService } from '../services/review-api.service';

interface ReviewStore {
  reviews: Review[];
  totalReviews: number;
  currentReview: Review | null;
  findings: Finding[];
  summary: ReviewSummary | null;
  progressLogs: LogEntry[];
  loading: boolean;
  error: string | null;
  selectedFindingIds: string[];
  filterSeverity: string | null;
  filterCategory: string | null;
  activeTab: number;
}

const initialState: ReviewStore = {
  reviews: [],
  totalReviews: 0,
  currentReview: null,
  findings: [],
  summary: null,
  progressLogs: [],
  loading: false,
  error: null,
  selectedFindingIds: [],
  filterSeverity: null,
  filterCategory: null,
  activeTab: 0,
};

export const ReviewSignalStore = signalStore(
  { providedIn: 'root' },
  withState(initialState),
  withComputed((store) => ({
    filteredFindings: computed(() => {
      let items = store.findings();
      const sev = store.filterSeverity();
      const cat = store.filterCategory();
      if (sev) items = items.filter((f) => f.severity === sev);
      if (cat) items = items.filter((f) => f.category === cat);
      return items;
    }),
    pendingFindings: computed(() =>
      store.findings().filter((f) => f.approval_status === 'pending')
    ),
    approvedFindings: computed(() =>
      store.findings().filter((f) => f.approval_status === 'approved')
    ),
    rejectedFindings: computed(() =>
      store.findings().filter((f) => f.approval_status === 'rejected')
    ),
    criticalCount: computed(() =>
      store.findings().filter((f) => f.severity === 'critical').length
    ),
    highCount: computed(() =>
      store.findings().filter((f) => f.severity === 'high').length
    ),
    isRunning: computed(() => store.currentReview()?.status === 'running'),
    isCompleted: computed(() => store.currentReview()?.status === 'completed'),
  })),
  withMethods((store) => {
    const api = inject(ReviewApiService);
    return {
      async loadReviews(page = 1) {
        patchState(store, { loading: true, error: null });
        try {
          const res: PagedResponse<Review> = await firstValueFrom(api.listReviews(page));
          patchState(store, { reviews: res.items, totalReviews: res.total, loading: false });
        } catch (e: any) {
          patchState(store, { loading: false, error: e.message });
        }
      },
      async loadReview(id: string) {
        patchState(store, { loading: true });
        try {
          const review = await firstValueFrom(api.getReview(id));
          patchState(store, { currentReview: review, loading: false });
        } catch (e: any) {
          patchState(store, { loading: false, error: e.message });
        }
      },
      async cancelReview(id: string) {
        try {
          const updated = await firstValueFrom(api.cancelReview(id));
          patchState(store, {
            reviews: store.reviews().map((r) => (r.id === id ? updated : r)),
          });
          if (store.currentReview()?.id === id) {
            patchState(store, { currentReview: updated });
          }
        } catch (e: any) {
          patchState(store, { error: e.message });
        }
      },
      async deleteReview(id: string) {
        try {
          await firstValueFrom(api.deleteReview(id));
          patchState(store, {
            reviews: store.reviews().filter((r) => r.id !== id),
            totalReviews: Math.max(0, store.totalReviews() - 1),
          });
          if (store.currentReview()?.id === id) {
            patchState(store, { currentReview: null });
          }
        } catch (e: any) {
          patchState(store, { error: e.message });
        }
      },
      async loadFindings(reviewId: string) {
        try {
          const res = await firstValueFrom(api.getFindings(reviewId));
          patchState(store, { findings: res.items });
        } catch (e: any) {
          patchState(store, { error: e.message });
        }
      },
      async loadSummary(reviewId: string) {
        try {
          const summary = await firstValueFrom(api.getSummary(reviewId));
          patchState(store, { summary });
        } catch (e: any) {
          patchState(store, { error: e.message });
        }
      },
      appendLog(log: LogEntry) {
        patchState(store, { progressLogs: [...store.progressLogs(), log] });
      },
      updateCurrentReview(patch: Partial<Review>) {
        const current = store.currentReview();
        if (current) patchState(store, { currentReview: { ...current, ...patch } });
      },
      setFilter(severity: string | null, category: string | null) {
        patchState(store, { filterSeverity: severity, filterCategory: category });
      },
      toggleFindingSelection(id: string) {
        const sel = store.selectedFindingIds();
        const next = sel.includes(id) ? sel.filter((x) => x !== id) : [...sel, id];
        patchState(store, { selectedFindingIds: next });
      },
      selectAllFindings() {
        patchState(store, {
          selectedFindingIds: store.filteredFindings().map((f) => f.id),
        });
      },
      clearSelection() {
        patchState(store, { selectedFindingIds: [] });
      },
      updateFinding(updated: Finding) {
        patchState(store, {
          findings: store.findings().map((f) => (f.id === updated.id ? updated : f)),
        });
      },
      setActiveTab(tab: number) {
        patchState(store, { activeTab: tab });
      },
      clearLogs() {
        patchState(store, { progressLogs: [] });
      },
    };
  })
);
