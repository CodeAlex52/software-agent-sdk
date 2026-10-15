import { WorktreesClient } from '../clients';
import type { ConversationWorktree } from '../clients';

const originalFetch = global.fetch;

afterEach(() => {
  global.fetch = originalFetch;
});

describe('WorktreesClient', () => {
  it('lists worktrees and removes one by name', async () => {
    const worktree: ConversationWorktree = {
      name: 'c0ffee',
      path: '/tmp/conversation-worktrees/c0ffee/repo',
      repository: '/home/me/repo',
      branch: 'openhands/c0ffee',
      conversation_ids: ['c0ffee'],
      last_activity: null,
      size_bytes: 1024,
      has_changes: false,
      in_use: false,
    };
    global.fetch = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify([worktree]), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        })
      )
      .mockResolvedValueOnce(new Response(null, { status: 204 })) as typeof fetch;
    const client = new WorktreesClient({ host: 'http://example.com/' });

    await expect(client.listWorktrees()).resolves.toEqual([worktree]);
    await client.removeWorktree('c0ffee');

    expect(global.fetch).toHaveBeenNthCalledWith(
      1,
      'http://example.com/api/worktrees',
      expect.objectContaining({ method: 'GET' })
    );
    expect(global.fetch).toHaveBeenNthCalledWith(
      2,
      'http://example.com/api/worktrees/c0ffee',
      expect.objectContaining({ method: 'DELETE' })
    );
  });

  it('surfaces a refused removal', async () => {
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: 'It has uncommitted or untracked changes' }), {
        status: 409,
        headers: { 'content-type': 'application/json' },
      })
    ) as typeof fetch;

    await expect(
      new WorktreesClient({ host: 'http://example.com' }).removeWorktree('c0ffee')
    ).rejects.toMatchObject({ status: 409, detail: 'It has uncommitted or untracked changes' });
  });
});
