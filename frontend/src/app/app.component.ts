import { Component, ChangeDetectionStrategy } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { CommonModule } from '@angular/common';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [RouterOutlet, RouterLink, RouterLinkActive, CommonModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="app-shell">
      <!-- Sidebar Navigation -->
      <nav class="sidebar">
        <div class="sidebar-logo">
          <div class="logo-icon">
            <svg width="26" height="26" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <!-- Outer glowing hexagonal shield -->
              <path d="M12 2L3.5 7V17L12 22L20.5 17V7L12 2Z" fill="url(#shield-bg)" stroke="url(#shield-border)" stroke-width="1.5" stroke-linejoin="round"/>
              <!-- Inner AI node network & checkmark -->
              <path d="M12 6L7.5 9.5V14.5L12 18L16.5 14.5V9.5L12 6Z" fill="url(#inner-node)" fill-opacity="0.3" stroke="url(#inner-node)" stroke-width="1.2"/>
              <!-- Central Code Verification Spark -->
              <path d="M9 12L11 14L15.5 9.5" stroke="#38bdf8" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
              <circle cx="12" cy="12" r="8.5" stroke="#a855f7" stroke-width="1" stroke-dasharray="2 3" opacity="0.5"/>
              <defs>
                <linearGradient id="shield-bg" x1="3.5" y1="2" x2="20.5" y2="22" gradientUnits="userSpaceOnUse">
                  <stop stop-color="#1e1b4b"/>
                  <stop offset="1" stop-color="#0f172a"/>
                </linearGradient>
                <linearGradient id="shield-border" x1="3.5" y1="2" x2="20.5" y2="22" gradientUnits="userSpaceOnUse">
                  <stop stop-color="#818cf8"/>
                  <stop offset="0.5" stop-color="#6366f1"/>
                  <stop offset="1" stop-color="#38bdf8"/>
                </linearGradient>
                <linearGradient id="inner-node" x1="7.5" y1="6" x2="16.5" y2="18" gradientUnits="userSpaceOnUse">
                  <stop stop-color="#c084fc"/>
                  <stop offset="1" stop-color="#6366f1"/>
                </linearGradient>
              </defs>
            </svg>
          </div>
          <div class="logo-text-wrapper">
            <span class="logo-text">Review<span class="logo-ai">AI</span></span>
            <span class="logo-tagline">Code Intelligence</span>
          </div>
        </div>

        <div class="nav-section">
          <span class="nav-label">Navigation</span>
          <a routerLink="/dashboard" routerLinkActive="active" class="nav-item">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/>
              <rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/>
            </svg>
            Dashboard
          </a>
          <a routerLink="/pending-prs" routerLinkActive="active" class="nav-item">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="18" cy="18" r="3"/>
              <circle cx="6" cy="6" r="3"/>
              <path d="M13 6h3a2 2 0 0 1 2 2v7"/>
              <line x1="6" y1="9" x2="6" y2="21"/>
            </svg>
            Pending PRs
          </a>
          <a routerLink="/settings" routerLinkActive="active" class="nav-item">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="12" cy="12" r="3"/>
              <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>
            </svg>
            Settings
          </a>
        </div>

        <div class="sidebar-footer">
          <div class="version-badge">v1.0.0</div>
        </div>
      </nav>

      <!-- Main Content -->
      <main class="main-content">
        <router-outlet/>
      </main>
    </div>
  `,
  styles: [`
    .app-shell {
      display: flex;
      height: 100vh;
      overflow: hidden;
    }

    .sidebar {
      width: 240px;
      flex-shrink: 0;
      background: rgba(15,20,32,0.95);
      border-right: 1px solid var(--color-border);
      display: flex;
      flex-direction: column;
      padding: 20px 0;
      backdrop-filter: blur(20px);
    }

    .sidebar-logo {
      display: flex;
      align-items: center;
      gap: 12px;
      padding: 8px 20px 24px;
      border-bottom: 1px solid var(--color-border);
      margin-bottom: 16px;
    }

    .logo-icon {
      width: 42px;
      height: 42px;
      background: radial-gradient(circle at 30% 30%, rgba(99,102,241,0.25), rgba(15,23,42,0.8));
      border-radius: 12px;
      display: flex;
      align-items: center;
      justify-content: center;
      color: white;
      border: 1px solid rgba(99,102,241,0.3);
      box-shadow: 0 4px 20px rgba(99,102,241,0.25), inset 0 1px 1px rgba(255,255,255,0.15);
      transition: transform var(--transition-fast), box-shadow var(--transition-fast);

      &:hover {
        transform: translateY(-1px) scale(1.02);
        box-shadow: 0 6px 24px rgba(99,102,241,0.4), inset 0 1px 1px rgba(255,255,255,0.25);
      }
    }

    .logo-text-wrapper {
      display: flex;
      flex-direction: column;
    }

    .logo-text {
      font-size: 1.15rem;
      font-weight: 800;
      letter-spacing: -0.02em;
      color: #ffffff;
      line-height: 1.1;
    }

    .logo-ai {
      background: linear-gradient(135deg, #818cf8 0%, #38bdf8 100%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      font-weight: 900;
      margin-left: 1px;
    }

    .logo-tagline {
      font-size: 0.62rem;
      font-weight: 600;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: #94a3b8;
      margin-top: 2px;
    }

    .nav-section {
      padding: 0 12px;
      flex: 1;
    }

    .nav-label {
      font-size: 0.65rem;
      font-weight: 700;
      color: var(--color-text-muted);
      text-transform: uppercase;
      letter-spacing: 0.12em;
      padding: 0 8px;
      display: block;
      margin-bottom: 6px;
    }

    .nav-item {
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 10px 12px;
      border-radius: var(--radius-md);
      color: var(--color-text-secondary);
      text-decoration: none;
      font-size: 0.875rem;
      font-weight: 500;
      transition: all var(--transition-fast);
      margin-bottom: 2px;

      svg { flex-shrink: 0; }

      &:hover {
        color: var(--color-text-primary);
        background: rgba(255,255,255,0.05);
      }

      &.active {
        color: var(--color-primary-light);
        background: rgba(99,102,241,0.12);
        border: 1px solid rgba(99,102,241,0.20);
      }
    }

    .sidebar-footer {
      padding: 16px 20px 0;
      border-top: 1px solid var(--color-border);
    }

    .version-badge {
      font-size: 0.7rem;
      color: var(--color-text-muted);
    }

    .main-content {
      flex: 1;
      min-width: 0;
      overflow-y: auto;
      overflow-x: hidden;
      background: var(--color-bg);
    }
  `]
})
export class AppComponent {}
