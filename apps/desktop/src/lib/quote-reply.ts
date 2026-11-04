import { type ComposerTarget, requestComposerFocus, requestComposerInsert } from '@/app/chat/composer/focus'
import { formatRefValue } from '@/components/assistant-ui/directive-text'
import { $composerQuotes, setComposerQuote } from '@/store/composer'

/**
 * Derive the chip label for a quote selection.
 *
 * Whitespace runs (including newlines) collapse to single spaces; the result is
 * sliced to 24 characters *including* the trailing ellipsis when truncated. A
 * label already present in `taken` gets a `-2`, `-3`, … suffix.
 */
export function deriveQuoteLabel(text: string, taken: Record<string, unknown>): string {
  const collapsed = text.replace(/\s+/g, ' ')

  // 24 chars total: 23 chars + the ellipsis.
  const base = collapsed.length > 24 ? collapsed.slice(0, 23) + '…' : collapsed

  let candidate = base
  let counter = 2

  while (taken[candidate] !== undefined) {
    candidate = `${base}-${counter}`
    counter++
  }

  return candidate
}

/**
 * Render a quoted selection as a Markdown blockquote.
 *
 * Blank lines drop out entirely; every remaining line gets a `> ` prefix. The
 * whole block is hard-capped at 2000 characters, with a trailing `…` marking
 * the cut (2001 characters total in the capped case).
 */
export function quoteToBlockquote(text: string): string {
  const result = text
    .split('\n')
    .filter(line => line.trim() !== '')
    .map(line => `> ${line}`)
    .join('\n')

  return result.length > 2000 ? result.slice(0, 2000) + '…' : result
}

/**
 * Store the selected text as a quote and insert its `@quote:` chip into the
 * target composer. Empty/whitespace-only selections are a no-op so callers can
 * wire this to a selection action without a guard of their own.
 */
export function insertQuoteReply(selection: string, opts?: { target?: ComposerTarget | 'active' }): boolean {
  const trimmed = selection.trim()

  if (!trimmed) {
    return false
  }

  const label = deriveQuoteLabel(trimmed, $composerQuotes.get())
  setComposerQuote(label, trimmed)

  const target = opts?.target ?? 'active'

  requestComposerInsert('@quote:' + formatRefValue(label), { mode: 'inline', target })
  requestComposerFocus(target)

  return true
}
