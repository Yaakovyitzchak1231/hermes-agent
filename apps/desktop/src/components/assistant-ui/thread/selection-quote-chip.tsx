import './selection-quote-chip.css'

import { useEffect, useRef, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Codicon } from '@/components/ui/codicon'
import { useI18n } from '@/i18n'
import { insertQuoteReply } from '@/lib/quote-reply'

/**
 * Returns true when the node is inside an assistant message root,
 * excluding roots that are inside a dialog content area.
 */
export function isInsideAssistantMessage(node: Node | null): boolean {
  if (!node) {return false}
  
  const assistantRoot = node instanceof Element
    ? node.closest('[data-slot="aui_assistant-message-root"]')
    : null
  
  if (!assistantRoot) {return false}
  
  // Exclude if this root is inside dialog content
  return !assistantRoot.closest('[data-slot="dialog-content"]')
}

/**
 * Returns a quote candidate selection from the given Selection object,
 * or null if the selection is not eligible for quoting.
 */
export function selectionQuoteCandidate(selection: Selection | null): { text: string; rect: DOMRect } | null {
  if (!selection || selection.isCollapsed) {return null}
  
  const text = selection.toString().trim()

  if (!text) {return null}
  
  const range = selection.getRangeAt(0)
  
  // Resolve the containing root element for each node
  const resolveContainingRoot = (node: Node): Element | null => {
    if (node instanceof Element) {
      return node.closest('[data-slot="aui_assistant-message-root"]')
    }

    return (node as any).parentElement?.closest('[data-slot="aui_assistant-message-root"]')
  }
  
  const startRoot = resolveContainingRoot(range.startContainer)
  const endRoot = resolveContainingRoot(range.endContainer)
  
  // Valid if both resolve to the SAME non-null root element AND that root is not inside dialog-content
  if (startRoot && endRoot && startRoot === endRoot) {
    if (!startRoot.closest('[data-slot="dialog-content"]')) {
      return { text, rect: range.getBoundingClientRect() }
    }
  }
  
  return null
}

export function SelectionQuoteChip() {
  const { t } = useI18n()
  const chipRef = useRef<HTMLDivElement>(null)
  const [candidate, setCandidate] = useState<{ text: string; rect: DOMRect } | null>(null)

  // Recompute on selection change only (rAF-throttled to one pass per frame).
  // Streaming DOM mutations under a live selection are left alone until the
  // next selectionchange — that is enough to keep the chip honest.
  useEffect(() => {
    let frame = 0

    const handleSelectionChange = () => {
      if (frame) {return}

      frame = requestAnimationFrame(() => {
        frame = 0
        setCandidate(selectionQuoteCandidate(window.getSelection()))
      })
    }

    document.addEventListener('selectionchange', handleSelectionChange)

    return () => {
      document.removeEventListener('selectionchange', handleSelectionChange)

      if (frame) {cancelAnimationFrame(frame)}
    }
  }, [])

  // Dismiss on scroll (capture)
  useEffect(() => {
    const handleScroll = () => setCandidate(null)

    document.addEventListener('scroll', handleScroll, true)

    return () => {
      document.removeEventListener('scroll', handleScroll, true)
    }
  }, [])

  // Dismiss on outside mousedown
  useEffect(() => {
    const handleMouseDown = (event: MouseEvent) => {
      if (chipRef.current && !chipRef.current.contains(event.target as Node)) {setCandidate(null)}
    }

    document.addEventListener('mousedown', handleMouseDown)

    return () => {
      document.removeEventListener('mousedown', handleMouseDown)
    }
  }, [])

  // Dismiss on Escape
  useEffect(() => {
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {setCandidate(null)}
    }

    document.addEventListener('keydown', handleEscape)

    return () => {
      document.removeEventListener('keydown', handleEscape)
    }
  }, [])

  if (!candidate) {return null}

  const handleClick = () => {
    if (candidate) {insertQuoteReply(candidate.text)}

    // Hide the chip but leave the user's selection intact (Claude-app behavior).
    setCandidate(null)
  }
  
  return (
    <div
      className="selection-quote-chip"
      ref={chipRef}
      style={{
        position: 'fixed',
        left: candidate.rect.left,
        top: candidate.rect.top,
        transform: 'translateY(-100%) translateY(-8px)'
      }}
    >
      <Button
        className="selection-quote-chip__button"
        onClick={handleClick}
        size="xs"
        variant="floating"
      >
        <Codicon className="mr-1" name="comment" size="0.875rem" />
        {t.contextMenu.replyToSelection}
      </Button>
    </div>
  )
}