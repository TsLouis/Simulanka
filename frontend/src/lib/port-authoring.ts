import type { PortDTO, RegistryDescriptorDTO } from './types'
import type { UpdatePortRequest } from './object-authoring'

export interface PortEditDraft {
  name: string
  direction: 'in' | 'out'
  portType: string
  label: string
  shape: string
  confidence: string
}

export interface PortDraftValidation {
  valid: boolean
  reason: string | null
}

export function draftFromPort(port: PortDTO): PortEditDraft {
  const shape = Array.isArray(port.attrs.shape)
    ? (port.attrs.shape as unknown[]).join('×')
    : ''
  return {
    name: port.name,
    direction: port.side,
    portType: port.port_type || 'any',
    label: typeof port.attrs.label === 'string' ? port.attrs.label : '',
    shape,
    confidence: typeof port.attrs.confidence === 'string' ? port.attrs.confidence : '',
  }
}

export function allowedPortTypes(descriptor: RegistryDescriptorDTO | null): string[] {
  const types = descriptor?.port_types?.filter(Boolean) ?? []
  return types.length > 0 ? types : ['any']
}

export function validatePortDraft(
  draft: PortEditDraft,
  descriptor: RegistryDescriptorDTO | null,
): PortDraftValidation {
  if (!draft.name.trim()) return { valid: false, reason: 'Port name is required.' }
  const allowed = allowedPortTypes(descriptor)
  if (!allowed.includes(draft.portType)) {
    return { valid: false, reason: `Unknown port type: ${draft.portType}` }
  }
  if (draft.shape.trim()) {
    const dims = draft.shape.trim().split(/[x×,\s]+/).filter(Boolean)
    if (dims.length === 0 || dims.some(value => !/^\d+$/.test(value) || Number(value) <= 0)) {
      return { valid: false, reason: 'Shape must contain positive integer dimensions.' }
    }
  }
  return { valid: true, reason: null }
}

export function updateRequestFromDraft(
  port: PortDTO,
  draft: PortEditDraft,
): UpdatePortRequest {
  const attrs = { ...port.attrs }
  if (draft.label.trim()) attrs.label = draft.label.trim()
  else delete attrs.label

  if (draft.confidence.trim()) attrs.confidence = draft.confidence.trim()
  else delete attrs.confidence

  if (draft.shape.trim()) {
    attrs.shape = draft.shape
      .trim()
      .split(/[x×,\s]+/)
      .filter(Boolean)
      .map(value => Number(value))
  } else {
    delete attrs.shape
  }

  return {
    name: draft.name.trim(),
    direction: draft.direction,
    port_type: draft.portType,
    attrs,
  }
}
