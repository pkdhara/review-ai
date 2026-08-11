import { Routes } from '@angular/router';

export const routes: Routes = [
  { path: '', redirectTo: 'dashboard', pathMatch: 'full' },
  {
    path: 'dashboard',
    loadComponent: () =>
      import('./features/dashboard/dashboard.component').then((m) => m.DashboardComponent),
  },
  {
    path: 'reviews/:id/progress',
    loadComponent: () =>
      import('./features/review-progress/review-progress.component').then(
        (m) => m.ReviewProgressComponent
      ),
  },
  {
    path: 'reviews/:id/results',
    loadComponent: () =>
      import('./features/review-results/review-results.component').then(
        (m) => m.ReviewResultsComponent
      ),
  },
  {
    path: 'reviews/:id/approval',
    loadComponent: () =>
      import('./features/comment-approval/comment-approval.component').then(
        (m) => m.CommentApprovalComponent
      ),
  },
  {
    path: 'settings',
    loadComponent: () =>
      import('./features/settings/settings.component').then((m) => m.SettingsComponent),
  },
  { path: '**', redirectTo: 'dashboard' },
];
