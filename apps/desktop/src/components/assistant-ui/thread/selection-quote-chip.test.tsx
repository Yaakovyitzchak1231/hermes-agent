import { act, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { isInsideAssistantMessage, selectionQuoteCandidate, SelectionQuoteChip } from './selection-quote-chip'

vi.mock('@/lib/quote-reply', () => ({ insertQuoteReply: vi.fn() }))
vi.mock('@/i18n', () => ({ useI18n: () => ({ t: { contextMenu: { replyToSelection: 'Reply to selection' } } }) }))

const ASSISTANT_ROOT = 'aui_assistant-message-root'

function assistantRoot(slot = ASSISTANT_ROOT) {
  const root = document.createElement('div')
  root.setAttribute('data-slot', slot)

  return root
}

function selectionFixture(startNode: Node, endNode: Node, text = 'selected text') {
  const range = {
    startContainer: startNode,
    endContainer: endNode,
    getBoundingClientRect: () => ({ left: 100, top: 200 } as DOMRect)
  }

  return {
    isCollapsed: false,
    toString: () => text,
    getRangeAt: () => range,
    removeAllRanges: vi.fn()
  }
}

afterEach(() => {
  document.body.innerHTML = ''
  vi.restoreAllMocks()
})

describe('isInsideAssistantMessage', () => {
  it('is true for a node inside an assistant message root', () => {
    const root = assistantRoot()
    const paragraph = document.createElement('p')
    root.appendChild(paragraph)

    expect(isInsideAssistantMessage(paragraph)).toBe(true)
  })

  it('is false for a node inside an assistant root wrapped in dialog-content', () => {
    const dialog = document.createElement('div')
    dialog.setAttribute('data-slot', 'dialog-content')
    const root = assistantRoot()
    const paragraph = document.createElement('p')
    root.appendChild(paragraph)
    dialog.appendChild(root)

    expect(isInsideAssistantMessage(paragraph)).toBe(false)
  })

  it('is false for a node inside a user message root', () => {
    const root = assistantRoot('aui_user-message-root')
    const paragraph = document.createElement('p')
    root.appendChild(paragraph)

    expect(isInsideAssistantMessage(paragraph)).toBe(false)
  })
})

describe('selectionQuoteCandidate', () => {
  it('returns null for a null selection', () => {
    expect(selectionQuoteCandidate(null)).toBe(null)
  })

  it('returns null for a collapsed selection', () => {
    expect(selectionQuoteCandidate({ isCollapsed: true, toString: () => 'x', getRangeAt: () => ({}) } as any)).toBe(null)
  })

  it('returns null for blank text', () => {
    const root = assistantRoot()
    const p = document.createElement('p')
    root.appendChild(p)

    expect(selectionQuoteCandidate(selectionFixture(p, p, '   ') as any)).toBe(null)
  })

  it('returns a candidate inside one assistant root', () => {
    const root = assistantRoot()
    const p = document.createElement('p')
    root.appendChild(p)

    const result = selectionQuoteCandidate(selectionFixture(p, p) as any)

    expect(result).not.toBe(null)
    expect(result?.text).toBe('selected text')
    expect(result?.rect.left).toBe(100)
  })

  it('returns a candidate for a cross-paragraph selection within the same root', () => {
    const root = assistantRoot()
    const first = document.createElement('p')
    const second = document.createElement('p')
    root.appendChild(first)
    root.appendChild(second)

    const result = selectionQuoteCandidate(selectionFixture(first, second) as any)

    expect(result).not.toBe(null)
    expect(result?.text).toBe('selected text')
  })

  it('returns null for a selection spanning two different roots', () => {
    const firstRoot = assistantRoot()
    const secondRoot = assistantRoot()
    const first = document.createElement('p')
    const second = document.createElement('p')
    firstRoot.appendChild(first)
    secondRoot.appendChild(second)

    expect(selectionQuoteCandidate(selectionFixture(first, second) as any)).toBe(null)
  })

  it('returns null for a selection inside a user message root', () => {
    const root = assistantRoot('aui_user-message-root')
    const p = document.createElement('p')
    root.appendChild(p)

    expect(selectionQuoteCandidate(selectionFixture(p, p) as any)).toBe(null)
  })

  it('returns null for a selection inside a dialog-content assistant root', () => {
    const dialog = document.createElement('div')
    dialog.setAttribute('data-slot', 'dialog-content')
    const root = assistantRoot()
    const p = document.createElement('p')
    root.appendChild(p)
    dialog.appendChild(root)

    expect(selectionQuoteCandidate(selectionFixture(p, p) as any)).toBe(null)
  })
})

describe('SelectionQuoteChip', () => {
  async function showChipFor(selection: ReturnType<typeof selectionFixture>) {
    vi.spyOn(window, 'getSelection').mockReturnValue(selection as any)

    const view = render(<SelectionQuoteChip />)

    await act(async () => {
      document.dispatchEvent(new Event('selectionchange'))
      await new Promise(resolve => setTimeout(resolve, 50))
    })

    return view
  }

  it('renders nothing with no candidate', () => {
    vi.spyOn(window, 'getSelection').mockReturnValue({
      isCollapsed: true,
      toString: () => '',
      getRangeAt: () => ({})
    } as any)

    const { container } = render(<SelectionQuoteChip />)

    expect(container.firstChild).toBeNull()
  })

  it('renders the Reply button after a selectionchange over an assistant message', async () => {
    const root = assistantRoot()
    const p = document.createElement('p')
    root.appendChild(p)

    await showChipFor(selectionFixture(p, p))

    expect(screen.getByText('Reply to selection')).toBeTruthy()
  })

  it('click inserts the quote, hides the chip and keeps the selection', async () => {
    const { insertQuoteReply } = await import('@/lib/quote-reply')
    const root = assistantRoot()
    const p = document.createElement('p')
    root.appendChild(p)
    const selection = selectionFixture(p, p)

    const { container } = await showChipFor(selection)

    await act(async () => {
      screen.getByText('Reply to selection').click()
      await new Promise(resolve => setTimeout(resolve, 10))
    })

    expect(vi.mocked(insertQuoteReply)).toHaveBeenCalledWith('selected text')
    expect(selection.removeAllRanges).not.toHaveBeenCalled()
    expect(container.firstChild).toBeNull()
  })

  it('Escape dismisses the chip', async () => {
    const root = assistantRoot()
    const p = document.createElement('p')
    root.appendChild(p)

    const { container } = await showChipFor(selectionFixture(p, p))
    expect(screen.getByText('Reply to selection')).toBeTruthy()

    await act(async () => {
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
      await new Promise(resolve => setTimeout(resolve, 10))
    })

    expect(container.firstChild).toBeNull()
  })
})
