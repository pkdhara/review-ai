import { Injectable } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import {
  AppSettings,
  Finding,
  PagedResponse,
  PendingPrsResponse,
  Review,
  ReviewSummary,
  StartReviewRequest,
} from '../models/models';
import { environment } from '../../../environments/environment';

@Injectable({ providedIn: 'root' })
export class ReviewApiService {
  private readonly base = environment.apiUrl;

  constructor(private http: HttpClient) {}

  getPendingPrs(onlyInternalReview = true, authorOnly = false): Observable<PendingPrsResponse> {
    let params = new HttpParams().set('only_internal_review', onlyInternalReview);
    if (authorOnly) {
      params = params.set('author_only', true);
    }
    return this.http.get<PendingPrsResponse>(`${this.base}/reviews/pending-prs`, { params });
  }

  startReview(req: StartReviewRequest): Observable<Review> {
    return this.http.post<Review>(`${this.base}/reviews/start`, req);
  }

  listReviews(page = 1, pageSize = 20): Observable<PagedResponse<Review>> {
    const params = new HttpParams().set('page', page).set('page_size', pageSize);
    return this.http.get<PagedResponse<Review>>(`${this.base}/reviews`, { params });
  }

  getReview(id: string): Observable<Review> {
    return this.http.get<Review>(`${this.base}/reviews/${id}`);
  }

  cancelReview(id: string): Observable<Review> {
    return this.http.post<Review>(`${this.base}/reviews/${id}/cancel`, {});
  }

  deleteReview(id: string): Observable<{ message: string; id: string }> {
    return this.http.delete<{ message: string; id: string }>(`${this.base}/reviews/${id}`);
  }

  getFindings(
    reviewId: string,
    severity?: string,
    category?: string
  ): Observable<{ items: Finding[]; total: number }> {
    let params = new HttpParams();
    if (severity) params = params.set('severity', severity);
    if (category) params = params.set('category', category);
    return this.http.get<{ items: Finding[]; total: number }>(
      `${this.base}/reviews/${reviewId}/findings`,
      { params }
    );
  }

  getSummary(reviewId: string): Observable<ReviewSummary> {
    return this.http.get<ReviewSummary>(`${this.base}/reviews/${reviewId}/summary`);
  }

  updateComment(findingId: string, editedComment: string): Observable<Finding> {
    return this.http.put<Finding>(`${this.base}/comments/${findingId}`, {
      edited_comment: editedComment,
    });
  }

  approveComments(findingIds: string[], approvedBy: string): Observable<{ message: string }> {
    return this.http.post<{ message: string }>(`${this.base}/comments/approve`, {
      finding_ids: findingIds,
      approved_by: approvedBy,
    });
  }

  rejectComments(findingIds: string[]): Observable<{ message: string }> {
    return this.http.post<{ message: string }>(`${this.base}/comments/reject`, {
      finding_ids: findingIds,
    });
  }

  publishComments(findingIds: string[]): Observable<{ message: string }> {
    return this.http.post<{ message: string }>(`${this.base}/comments/publish`, {
      finding_ids: findingIds,
    });
  }

  getSettings(): Observable<AppSettings> {
    return this.http.get<AppSettings>(`${this.base}/settings`);
  }

  updateSettings(settings: Partial<AppSettings> & Record<string, any>): Observable<AppSettings> {
    return this.http.put<AppSettings>(`${this.base}/settings`, settings);
  }

  streamProgress(reviewId: string): EventSource {
    return new EventSource(`${this.base}/reviews/${reviewId}/stream`);
  }
}
