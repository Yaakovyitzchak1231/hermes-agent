import { beforeEach, describe, expect, it, vi } from 'vitest'

import { deriveQuoteLabel, insertQuoteReply, quoteToBlockquote } from './quote-reply'

const mocks = vi.hoisted(() => ({
  requestComposerFocus: vi.fn(),
  requestComposerInsert: vi.fn(),
  setComposerQuote: vi.fn()
}))

vi.mock('@/store/composer', () => ({
  $composerQuotes: { get: () => ({}) },
  setComposerQuote: mocks.setComposerQuote
}))

vi.mock('@/app/chat/composer/focus', () => ({
  requestComposerFocus: mocks.requestComposerFocus,
  requestComposerInsert: mocks.requestComposerInsert
}))

describe('deriveQuoteLabel', () => {
  it('returns short text unchanged', () => {
    expect(deriveQuoteLabel('hi', {})).toBe('hi')
  })

  it('truncates to 24 chars total and adds … when truncated', () => {
    expect(deriveQuoteLabel('Run the tests now, please', {})).toBe('Run the tests now, plea…')
  })

  it('collapses whitespace runs to single spaces', () => {
    expect(deriveQuoteLabel('a\n\nb   c', {})).toBe('a b c')
  })

  it('appends -2 when label exists in taken', () => {
    expect(deriveQuoteLabel('Run the tests now', { 'Run the tests now': 1 })).toBe('Run the tests now-2')
  })

  it('appends -3 when -2 also exists in taken', () => {
    expect(deriveQuoteLabel('Run the tests now', { 'Run the tests now': 1, 'Run the tests now-2': 1 })).toBe(
      'Run the tests now-3'
    )
  })
})

describe('quoteToBlockquote', () => {
  it('drops blank lines and prefixes each line with > ', () => {
    expect(quoteToBlockquote('line1\n\nline2\nline3')).toBe('> line1\n> line2\n> line3')
  })

  it('caps at 2000 chars total with trailing … when capped', () => {
    const result = quoteToBlockquote('x'.repeat(2500))

    expect(result.length).toBe(2001)
    expect(result).toBe('> ' + 'x'.repeat(1998) + '…')
  })
})

describe('insertQuoteReply', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('returns false and does nothing when selection is empty after trim', () => {
    expect(insertQuoteReply('   ')).toBe(false)
    expect(mocks.setComposerQuote).not.toHaveBeenCalled()
    expect(mocks.requestComposerInsert).not.toHaveBeenCalled()
    expect(mocks.requestComposerFocus).not.toHaveBeenCalled()
  })

  it('sets composer quote and inserts @quote:chip with the active target', () => {
    expect(insertQuoteReply('hi')).toBe(true)
    expect(mocks.setComposerQuote).toHaveBeenCalledWith('hi', 'hi')
    expect(mocks.requestComposerInsert).toHaveBeenCalledWith('@quote:hi', { mode: 'inline', target: 'active' })
    expect(mocks.requestComposerFocus).toHaveBeenCalledWith('active')
  })

  it('uses a custom target when provided', () => {
    expect(insertQuoteReply('hi', { target: 'main' })).toBe(true)
    expect(mocks.setComposerQuote).toHaveBeenCalledWith('hi', 'hi')
    expect(mocks.requestComposerInsert).toHaveBeenCalledWith('@quote:hi', { mode: 'inline', target: 'main' })
    expect(mocks.requestComposerFocus).toHaveBeenCalledWith('main')
  })
})
