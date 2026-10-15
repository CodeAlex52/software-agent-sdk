import { HttpClient } from './http-client';

export interface WorktreesClientOptions {
  host: string;
  apiKey?: string;
  timeout?: number;
}

/** A directory under the Agent Server's worktree root (`GET /api/worktrees`). */
export interface ConversationWorktree {
  name: string;
  path: string;
  repository: string | null;
  branch: string | null;
  /** Empty for a leftover no conversation uses. */
  conversation_ids: string[];
  last_activity: string | null;
  size_bytes: number;
  /** Uncommitted or untracked changes; such a worktree is never removed. */
  has_changes: boolean;
  /** One of its conversations is loaded; removal is refused. */
  in_use: boolean;
}

export class WorktreesClient {
  public readonly host: string;
  public readonly apiKey?: string;
  private readonly client: HttpClient;

  constructor(options: WorktreesClientOptions) {
    this.host = options.host.replace(/\/$/, '');
    this.apiKey = options.apiKey;
    this.client = new HttpClient({
      baseUrl: this.host,
      apiKey: this.apiKey,
      timeout: options.timeout || 60000,
    });
  }

  async listWorktrees(): Promise<ConversationWorktree[]> {
    const response = await this.client.get<ConversationWorktree[]>('/api/worktrees');
    return response.data;
  }

  /**
   * Remove a worktree; its branch stays, and reopening one of its
   * conversations re-creates it. 409 while it has changes or a conversation
   * using it is open.
   */
  async removeWorktree(name: string): Promise<void> {
    await this.client.delete(`/api/worktrees/${encodeURIComponent(name)}`);
  }

  close(): void {
    this.client.close();
  }
}
