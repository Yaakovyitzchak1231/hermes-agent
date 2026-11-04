import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { referenceRe, WIRE_REFERENCE_KINDS } from '@/components/assistant-ui/reference-kinds'

import { UserMessageText } from './user-message-text'

afterEach(cleanup)

/**
 * A sent reference must render as the chip the composer showed. These cover the
 * seam where that used to break: the value's quoting is directive syntax, and a
 * surface that reads it as markdown splits one reference into two wrong things.
 */
describe('a sent reference renders as the chip the composer showed', () => {
  it('chips a backtick-quoted @url: instead of splitting it into code', () => {
    render(
      <UserMessageText text="@url:`https://github.com/NousResearch/hermes-agent/pull/74790` urls lose formatting" />
    )

    expect(screen.queryByTitle('https://github.com/NousResearch/hermes-agent/pull/74790')).not.toBeNull()
    // The whole reference is one node — no bare `@url:` text left behind.
    expect(document.body.textContent).not.toContain('@url:')
  })

  it('chips a backtick-quoted @file: path with spaces', () => {
    render(<UserMessageText text="see @file:`apps/desktop/my notes.md` please" />)

    expect(screen.queryByTitle('apps/desktop/my notes.md')).not.toBeNull()
    expect(document.body.textContent).not.toContain('@file:')
  })

  it('labels a large-paste file as pasted content, keeping its path on hover', () => {
    const path = '/home/u/.hermes/attachments/pasted_content_2026-09-27_21-33-42-827_55e028-2.txt'

    render(<UserMessageText text={`@file:${path}`} />)

    expect(screen.getByTitle(path).textContent).toBe('Pasted content')
  })

  it('chips every kind that travels in message text', () => {
    // The guard against WIRE_REFERENCE_KINDS and the pattern's own alternation
    // drifting apart: add a kind to one and this fails until both agree.
    for (const kind of WIRE_REFERENCE_KINDS) {
      expect(`@${kind}:\`some value\``.match(referenceRe()), kind).toHaveLength(1)
    }
  })

  it('still renders a genuine code span as code', () => {
    render(<UserMessageText text="run `npm test` first" />)

    const code = document.querySelector('[data-slot="aui_user-inline-code"]')

    expect(code?.textContent).toBe('npm test')
  })

  it('renders code and a reference side by side', () => {
    render(<UserMessageText text="run `npm test` on @file:`apps/desktop/a b.ts` now" />)

    expect(document.querySelector('[data-slot="aui_user-inline-code"]')?.textContent).toBe('npm test')
    expect(screen.queryByTitle('apps/desktop/a b.ts')).not.toBeNull()
  })

  it('leaves a fenced block alone', () => {
    render(<UserMessageText text={'before\n```ts\nconst x = 1\n```\nafter'} />)

    const fence = document.querySelector('[data-slot="aui_user-fence"]')

    expect(fence?.textContent).toBe('const x = 1\n')
    // #70451: a wide user fence wraps inside the bubble instead of growing a
    // horizontal scrollbar under the transcript.
    expect(fence?.className).toContain('overflow-x-hidden')
    expect(fence?.className).toContain('whitespace-pre-wrap')
    expect(fence?.className).not.toContain('overflow-x-auto')
  })
})
describe('blockquote rendering in sent user bubbles', () => {
  it('para\n> quoted line\n> more\nafter', () => {
    render(<UserMessageText text={'para\n> quoted line\n> more\nafter'} />)

    // The quote should be rendered
    const quote = document.querySelector('[data-slot="aui_user-quote"]')
    expect(quote).not.toBeNull()
    expect(quote?.textContent).toBe('quoted line\nmore')

    // para before
    expect(document.querySelector('[data-slot="aui_user-inline-text"]')?.textContent).toContain('para')
    // after — inline-text spans inside the quote block itself are excluded
    const inlineTexts = Array.from(document.querySelectorAll('[data-slot="aui_user-inline-text"]')).filter(
      el => !el.closest('[data-slot="aui_user-quote"]')
    )

    expect(inlineTexts[1]?.textContent).toContain('after')
  })

  it('quote with code span inside', () => {
    render(<UserMessageText text={'before\n> use `npm test`\nafter'} />)

    const quote = document.querySelector('[data-slot="aui_user-quote"]')
    expect(quote).not.toBeNull()
    expect(quote?.textContent).toBe('use npm test')

    // Should have both inline-text and inline-code in the quote
    const inlineCode = document.querySelector('[data-slot="aui_user-inline-code"]')
    expect(inlineCode).not.toBeNull()
    expect(inlineCode?.textContent).toBe('npm test')
  })

  it('>5 items stays as prose (no quote)', () => {
    render(<UserMessageText text=">5 items are not quotes" />)

    // Should NOT create a quote
    const quote = document.querySelector('[data-slot="aui_user-quote"]')
    expect(quote).toBeNull()

    // Should be inline text
    const inlineText = document.querySelector('[data-slot="aui_user-inline-text"]')
    expect(inlineText).not.toBeNull()
    expect(inlineText?.textContent).toBe('>5 items are not quotes')
  })

  it('fences keep precedence, >x inside fence stays fence', () => {
    render(<UserMessageText text={">x\n```\n> x inside fence\n```\n> y after"} />)

    const fence = document.querySelector('[data-slot="aui_user-fence"]')
    expect(fence).not.toBeNull()
    expect(fence?.textContent).toContain('> x inside fence')

    // The > y after should be a quote
    const quote = document.querySelector('[data-slot="aui_user-quote"]')
    expect(quote).not.toBeNull()
    expect(quote?.textContent).toBe('y after')
  })
})