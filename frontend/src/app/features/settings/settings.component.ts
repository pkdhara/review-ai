import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  inject,
  signal,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { firstValueFrom } from 'rxjs';
import { ReviewApiService } from '../../core/services/review-api.service';
import { AppSettings } from '../../core/models/models';

interface SettingsForm {
  bitbucket_access_token: string;
  bitbucket_workspace: string;
  jira_base_url: string;
  jira_email: string;
  jira_api_token: string;
  openai_api_key: string;
  anthropic_api_key: string;
  gemini_api_key: string;
  ai_provider: string;
}

@Component({
  selector: 'app-settings',
  standalone: true,
  imports: [CommonModule, FormsModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="settings-page">
      <header class="page-header fade-in">
        <h1>Settings</h1>
        <p class="text-secondary" style="margin-top:4px">Configure API credentials for integrations</p>
      </header>

      @if (loading()) {
        <div class="loading-state">
          <div class="spinner-lg"></div>
          <span>Loading settings...</span>
        </div>
      }

      <!-- Bitbucket -->
      <div class="card settings-card fade-in">
        <div class="card-header">
          <div class="settings-icon bitbucket">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
              <path d="M.778 1.213a.768.768 0 0 0-.768.892l3.263 19.81c.084.5.515.868 1.022.873H19.95a.772.772 0 0 0 .77-.646l3.27-20.03a.768.768 0 0 0-.768-.896L.778 1.213zm14.52 13.087H8.53l-1.805-9.476h10.123l-1.55 9.476z"/>
            </svg>
          </div>
          <div>
            <h3>Bitbucket</h3>
            <p class="text-muted" style="font-size:0.8rem; margin-top:2px">Connect to your Bitbucket workspace</p>
          </div>
          @if (settings()?.has_bitbucket_token) {
            <div class="connected-badge">✓ Connected</div>
          }
        </div>
        <div class="card-body settings-form">
          <div class="input-group">
            <label>Access Token</label>
            <input class="input" type="password" [(ngModel)]="form.bitbucket_access_token"
              placeholder="Enter Bitbucket access token" id="bitbucket-token"/>
          </div>
          <div class="input-group">
            <label>Workspace</label>
            <input class="input" type="text" [(ngModel)]="form.bitbucket_workspace"
              placeholder="your-workspace-name" id="bitbucket-workspace"/>
          </div>
        </div>
      </div>

      <!-- Jira -->
      <div class="card settings-card fade-in">
        <div class="card-header">
          <div class="settings-icon jira">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
              <path d="M11.571 11.513H0a5.218 5.218 0 0 0 5.232 5.215h2.13v2.059A5.215 5.215 0 0 0 12.575 24V12.518a1.005 1.005 0 0 0-1.004-1.005zm5.723-5.756H5.736a5.215 5.215 0 0 0 5.215 5.214h2.129v2.058a5.218 5.218 0 0 0 5.215 5.215V6.762a1.005 1.005 0 0 0-1.001-1.005zM23.013 0H11.455a5.215 5.215 0 0 0 5.215 5.215h2.129v2.059A5.215 5.215 0 0 0 24.019 12.49V1.005A1.005 1.005 0 0 0 23.013 0z"/>
            </svg>
          </div>
          <div>
            <h3>Jira</h3>
            <p class="text-muted" style="font-size:0.8rem; margin-top:2px">Fetch requirements from Jira stories</p>
          </div>
          @if (settings()?.has_jira_token) {
            <div class="connected-badge">✓ Connected</div>
          }
        </div>
        <div class="card-body settings-form">
          <div class="input-group" style="grid-column:1/-1">
            <label>Jira Base URL</label>
            <input class="input" type="url" [(ngModel)]="form.jira_base_url"
              placeholder="https://your-org.atlassian.net" id="jira-url"/>
          </div>
          <div class="input-group">
            <label>Email</label>
            <input class="input" type="email" [(ngModel)]="form.jira_email"
              placeholder="you@company.com" id="jira-email"/>
          </div>
          <div class="input-group">
            <label>API Token</label>
            <input class="input" type="password" [(ngModel)]="form.jira_api_token"
              placeholder="Enter Jira API token" id="jira-token"/>
          </div>
        </div>
      </div>

      <!-- AI Provider -->
      <div class="card settings-card fade-in">
        <div class="card-header">
          <div class="settings-icon ai">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M12 2a2 2 0 0 1 2 2c0 .74-.4 1.39-1 1.73V7h1a7 7 0 0 1 7 7h1a1 1 0 0 1 1 1v3a1 1 0 0 1-1 1h-1v1a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-1H2a1 1 0 0 1-1-1v-3a1 1 0 0 1 1-1h1a7 7 0 0 1 7-7h1V5.73c-.6-.34-1-.99-1-1.73a2 2 0 0 1 2-2z"/>
            </svg>
          </div>
          <div>
            <h3>AI Provider</h3>
            <p class="text-muted" style="font-size:0.8rem; margin-top:2px">Configure language model API keys</p>
          </div>
        </div>
        <div class="card-body settings-form">
          <div class="input-group" style="grid-column:1/-1">
            <label>Default Provider</label>
            <div class="provider-selector">
              <button class="provider-btn" [class.active]="form.ai_provider === 'gemini' || form.ai_provider === 'google'"
                (click)="form.ai_provider = 'gemini'" id="provider-gemini">
                <span class="provider-icon">💎</span> Gemini (Google)
              </button>
              <button class="provider-btn" [class.active]="form.ai_provider === 'anthropic'"
                (click)="form.ai_provider = 'anthropic'" id="provider-anthropic">
                <span class="provider-icon">🤖</span> Claude (Anthropic)
              </button>
              <button class="provider-btn" [class.active]="form.ai_provider === 'openai'"
                (click)="form.ai_provider = 'openai'" id="provider-openai">
                <span class="provider-icon">⚡</span> GPT-4 (OpenAI)
              </button>
            </div>
          </div>
          <div class="input-group">
            <label>Gemini API Key</label>
            <input class="input" type="password" [(ngModel)]="form.gemini_api_key"
              placeholder="AIzaSy..." id="gemini-key"/>
            @if (settings()?.has_gemini_key) { <span class="key-hint">✓ Key saved</span> }
          </div>
          <div class="input-group">
            <label>Anthropic API Key</label>
            <input class="input" type="password" [(ngModel)]="form.anthropic_api_key"
              placeholder="sk-ant-..." id="anthropic-key"/>
            @if (settings()?.has_anthropic_key) { <span class="key-hint">✓ Key saved</span> }
          </div>
          <div class="input-group">
            <label>OpenAI API Key</label>
            <input class="input" type="password" [(ngModel)]="form.openai_api_key"
              placeholder="sk-..." id="openai-key"/>
            @if (settings()?.has_openai_key) { <span class="key-hint">✓ Key saved</span> }
          </div>
        </div>
      </div>

      <!-- Save -->
      <div class="save-row fade-in">
        @if (successMsg()) {
          <div class="success-msg">✅ {{ successMsg() }}</div>
        }
        @if (errorMsg()) {
          <div class="error-msg">❌ {{ errorMsg() }}</div>
        }
        <button class="btn btn-primary btn-lg" (click)="save()" [disabled]="saving()" id="save-settings-btn">
          @if (saving()) {
            <span class="spinner-sm"></span> Saving...
          } @else {
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
              <polyline points="20 6 9 17 4 12"/>
            </svg>
            Save Settings
          }
        </button>
      </div>
    </div>
  `,
  styles: [`
    .settings-page { padding: 32px; max-width: 900px; margin: 0 auto; }
    .page-header { margin-bottom: 32px; }

    .loading-state {
      display: flex; align-items: center; gap: 12px; color: var(--color-text-muted);
      padding: 40px; justify-content: center;
    }
    .spinner-lg {
      width: 28px; height: 28px; border: 3px solid rgba(99,102,241,0.2);
      border-top-color: var(--color-primary); border-radius: 50%; animation: spin 1s linear infinite;
    }
    @keyframes spin { to { transform: rotate(360deg); } }

    .settings-card { margin-bottom: 20px; }

    .settings-icon {
      width: 44px; height: 44px; border-radius: var(--radius-md);
      display: flex; align-items: center; justify-content: center;
      flex-shrink: 0;

      &.bitbucket { background: rgba(32,112,243,0.12); color: #2070f3; border: 1px solid rgba(32,112,243,0.25); }
      &.jira { background: rgba(0,82,204,0.12); color: #0052cc; border: 1px solid rgba(0,82,204,0.25); }
      &.ai { background: rgba(99,102,241,0.12); color: var(--color-primary-light); border: 1px solid rgba(99,102,241,0.25); }
    }

    .card-header {
      display: flex; align-items: center; gap: 14px; padding: 20px 24px;
      border-bottom: 1px solid var(--color-border);
    }

    .connected-badge {
      margin-left: auto; background: rgba(34,197,94,0.12); color: #86efac;
      border: 1px solid rgba(34,197,94,0.25); border-radius: 100px;
      padding: 4px 12px; font-size: 0.75rem; font-weight: 700;
    }

    .settings-form {
      display: grid; grid-template-columns: 1fr 1fr; gap: 20px; padding: 24px;
    }

    .provider-selector { display: flex; gap: 8px; }
    .provider-btn {
      flex: 1; padding: 12px; border-radius: var(--radius-md);
      border: 1px solid var(--color-border); background: var(--color-surface-2);
      color: var(--color-text-secondary); cursor: pointer; font-size: 0.875rem;
      font-weight: 500; display: flex; align-items: center; justify-content: center; gap: 8px;
      transition: all var(--transition-fast);

      &.active {
        border-color: var(--color-primary); background: rgba(99,102,241,0.12);
        color: var(--color-primary-light);
      }
      &:hover:not(.active) { border-color: var(--color-border-2); color: var(--color-text-primary); }
    }

    .provider-icon { font-size: 1.1rem; }

    .key-hint { font-size: 0.72rem; color: #86efac; margin-top: 4px; }

    .save-row {
      display: flex; align-items: center; gap: 16px; justify-content: flex-end;
      padding: 24px 0;
    }

    .success-msg {
      font-size: 0.875rem; color: #86efac; background: rgba(34,197,94,0.10);
      border: 1px solid rgba(34,197,94,0.25); padding: 10px 16px; border-radius: var(--radius-md);
    }
    .error-msg {
      font-size: 0.875rem; color: #fca5a5; background: rgba(239,68,68,0.10);
      border: 1px solid rgba(239,68,68,0.25); padding: 10px 16px; border-radius: var(--radius-md);
    }

    .spinner-sm {
      width: 14px; height: 14px; border: 2px solid rgba(255,255,255,0.3);
      border-top-color: white; border-radius: 50%; animation: spin 0.8s linear infinite; display: inline-block;
    }
  `]
})
export class SettingsComponent implements OnInit {
  private readonly api = inject(ReviewApiService);

  settings = signal<AppSettings | null>(null);
  loading = signal(true);
  saving = signal(false);
  successMsg = signal<string | null>(null);
  errorMsg = signal<string | null>(null);

  form: SettingsForm = {
    bitbucket_access_token: '',
    bitbucket_workspace: '',
    jira_base_url: '',
    jira_email: '',
    jira_api_token: '',
    openai_api_key: '',
    anthropic_api_key: '',
    gemini_api_key: '',
    ai_provider: 'gemini',
  };

  ngOnInit() {
    this.loadSettings();
  }

  async loadSettings() {
    this.loading.set(true);
    try {
      const s = await firstValueFrom(this.api.getSettings());
      this.settings.set(s);
      this.form.bitbucket_workspace = s.bitbucket_workspace || '';
      this.form.jira_base_url = s.jira_base_url || '';
      this.form.jira_email = s.jira_email || '';
      this.form.ai_provider = s.ai_provider || 'gemini';
    } catch {
      this.errorMsg.set('Failed to load settings.');
    } finally {
      this.loading.set(false);
    }
  }

  async save() {
    this.saving.set(true);
    this.errorMsg.set(null);
    try {
      // Only send non-empty values to avoid blanking existing secrets
      const payload: Partial<SettingsForm> = {};
      const entries = Object.entries(this.form) as [keyof SettingsForm, string][];
      for (const [k, v] of entries) {
        if (v !== '') (payload as Record<string, string>)[k] = v;
      }
      const updated = await firstValueFrom(this.api.updateSettings(payload));
      this.settings.set(updated);
      this.successMsg.set('Settings saved successfully.');
      setTimeout(() => this.successMsg.set(null), 4000);
    } catch (e: any) {
      this.errorMsg.set(e?.error?.detail || 'Failed to save settings.');
    } finally {
      this.saving.set(false);
    }
  }
}
