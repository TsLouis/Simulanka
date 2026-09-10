import type { PresentationSpecDTO, RegistryDescriptorDTO } from './types'

export function resolveNodePresentation(
  descriptor: RegistryDescriptorDTO | null,
  profileKey: string,
): PresentationSpecDTO | null {
  if (!descriptor) return null
  const canonical = descriptor.aliases.node[profileKey] ?? profileKey
  const profile = descriptor.node_profiles.find(item => item.key === canonical)
  if (!profile?.presentation) return null
  return descriptor.presentations.find(item => item.key === profile.presentation) ?? null
}

export function orderedAttributeEntries(
  attrs: Record<string, unknown>,
  preferred: readonly string[],
): [string, unknown][] {
  const seen = new Set<string>()
  const entries: [string, unknown][] = []
  for (const key of preferred) {
    if (seen.has(key) || !(key in attrs)) continue
    seen.add(key)
    entries.push([key, attrs[key]])
  }
  for (const key of Object.keys(attrs).sort()) {
    if (seen.has(key)) continue
    entries.push([key, attrs[key]])
  }
  return entries
}
