// §13.6 verify-loop vocabulary shared by the header badge (App.svelte) and
// the panel list (VerifyPanel.svelte) — one predicate, no drift.
import type { EdgeDTO } from './types'

// Pending ghost = agent proposal still awaiting the human. A rejected ghost
// stays status=proposed (rejection ≠ deletion, §13.6) but carries the user's
// `wrong` verdict, which moves it to the disagreement set instead.
export const isPendingGhost = (e: EdgeDTO): boolean =>
  e.attrs.status === 'proposed' &&
  e.attrs.source === 'agent' &&
  !(e.attrs.verdict === 'wrong' && e.attrs.verdict_by === 'user')
