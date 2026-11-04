import { describe, expect, it } from 'vitest'

import { quoteReplyRow, resolveDomTarget } from './target'

describe('quoteReplyRow predicate', () => {
  it('returns true when inside a message root with selection text and no editable', () => {
    // Create a mock element inside a message root
    const messageRoot = document.createElement('div')
    messageRoot.setAttribute('data-slot', 'aui_assistant-message-root')
    
    const paragraph = document.createElement('p')
    paragraph.textContent = 'hello'
    messageRoot.appendChild(paragraph)
    
    // Mock the selection
    const mockSelection = {
      toString: () => 'x',
      rangeCount: 1,
      getRangeAt: () => ({ intersectsNode: () => true })
    }
    Object.defineProperty(window, 'getSelection', { value: () => mockSelection })
    
    const target = resolveDomTarget(paragraph)
    
    expect(target.insideMessageRoot).toBe(true)
    expect(target.selectionText).toBe('x')
    expect(target.editable).toBeNull()
    
    expect(quoteReplyRow(target)).toBe(true)
  })
  
  it('returns false when outside any message root', () => {
    const outsideElement = document.createElement('div')
    outsideElement.textContent = 'outside'
    
    const target = resolveDomTarget(outsideElement)
    
    expect(target.insideMessageRoot).toBe(false)
    expect(quoteReplyRow(target)).toBe(false)
  })
  
  it('returns false when editable is set', () => {
    const editable = document.createElement('textarea')
    editable.textContent = 'editable content'
    
    // Mock the selection to simulate text selection in the editable
    const mockSelection = {
      toString: () => 'editable content',
      rangeCount: 1
    }
    Object.defineProperty(window, 'getSelection', { value: () => mockSelection })
    
    const target = resolveDomTarget(editable)
    
    expect(target.insideMessageRoot).toBe(false) // Plain editable is NOT inside a message root
    expect(target.editable).toBe(editable)
    expect(target.selectionText).toBe('editable content')
    
    expect(quoteReplyRow(target)).toBe(false)
  })
  
  it('returns false with empty selection', () => {
    const messageRoot = document.createElement('div')
    messageRoot.setAttribute('data-slot', 'aui_assistant-message-root')
    
    const paragraph = document.createElement('p')
    paragraph.textContent = ''
    messageRoot.appendChild(paragraph)
    
    const mockSelection = {
      toString: () => '',
      rangeCount: 0
    }
    Object.defineProperty(window, 'getSelection', { value: () => mockSelection })
    
    const target = resolveDomTarget(paragraph)
    
    expect(target.insideMessageRoot).toBe(true)
    expect(target.selectionText).toBe('')
    
    expect(quoteReplyRow(target)).toBe(false)
  })
})