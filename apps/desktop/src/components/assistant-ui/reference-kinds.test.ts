import { describe, expect, it } from 'vitest'

import {
  referenceKind,
  referenceRe,
  referenceStyle,
  textWithoutReferenceLines,
  WIRE_REFERENCE_KINDS
} from './reference-kinds'

describe('quote reference kind', () => {
  it('recognises quoted and bare @quote: values in text', () => {
    expect('@quote:`x`'.match(referenceRe())).toHaveLength(1)
    expect('@quote:x'.match(referenceRe())).toHaveLength(1)
  })

  it('resolves to a quote kind with its own label', () => {
    expect(referenceKind('quote')).toBe('quote')
    expect(referenceStyle('quote').label).toBe('Quotes')
  })

  it('travels in message text as a wire kind', () => {
    expect(WIRE_REFERENCE_KINDS.includes('quote')).toBe(true)
  })

  it('is removed with the reference lines it occupies', () => {
    expect(textWithoutReferenceLines('hi\n@quote:`x`\nbye')).toBe('hi\nbye')
  })
})
