import type {
  AffordanceDTO,
  RegistryDescriptorDTO,
  TemplateSpecDTO,
} from './types'

export interface TemplatePort {
  name: string
  direction: 'in' | 'out'
  port_type?: string
}

export interface NodeTemplate {
  label: string
  name: string
  category: string
  type: string
  attrs: Record<string, unknown>
  ports: TemplatePort[]
  custom?: boolean
}

export interface TemplateGroup {
  category: string
  items: NodeTemplate[]
}

function canonicalNodeProfile(
  descriptor: RegistryDescriptorDTO,
  profile: string,
): string {
  return descriptor.aliases.node[profile] ?? profile
}

function placeableIn(
  descriptor: RegistryDescriptorDTO,
  profileKey: string,
  parentType: string | null,
): boolean {
  const canonical = canonicalNodeProfile(descriptor, profileKey)
  const profile = descriptor.node_profiles.find(item => item.key === canonical)
  // Custom templates can outlive an uninstalled package. Keep them visible;
  // the server remains the hard gate and will return unknown_profile.
  if (!profile) return true
  return profile.allow_parents.includes('*') || profile.allow_parents.includes(parentType)
}

function descriptorTemplate(item: TemplateSpecDTO): NodeTemplate {
  const torchLabel = item.key.startsWith('torch.')
    ? item.key.split('.').at(-1)
    : undefined
  return {
    label: torchLabel ?? item.name,
    name: item.name,
    category: item.category,
    type: item.profile,
    attrs: { ...item.default_attrs },
    ports: item.default_ports.map(port => ({
      name: port.name,
      direction: port.direction,
      port_type: port.port_type,
    })),
  }
}

// The server descriptor supplies the catalog and parent rules. The current
// container's resolved create affordance decides whether a catalog exists at
// all; POST /node revalidates the same action immediately before writing.
export function buildGroups(
  descriptor: RegistryDescriptorDTO | null,
  custom: Record<
    string,
    { category: string; type: string; attrs: Record<string, unknown>; ports: TemplatePort[] }
  >,
  parentType: string | null,
  createAffordance: AffordanceDTO | null,
): TemplateGroup[] {
  if (!descriptor || !createAffordance?.enabled) return []

  const groups = new Map<string, NodeTemplate[]>()
  for (const item of descriptor.templates) {
    if (!placeableIn(descriptor, item.profile, parentType)) continue
    const template = descriptorTemplate(item)
    const bucket = groups.get(template.category) ?? []
    bucket.push(template)
    groups.set(template.category, bucket)
  }
  for (const [name, item] of Object.entries(custom)) {
    if (!placeableIn(descriptor, item.type, parentType)) continue
    const category = item.category === 'custom' ? '我的模板' : item.category
    const bucket = groups.get(category) ?? []
    bucket.push({
      label: name,
      name,
      category,
      type: canonicalNodeProfile(descriptor, item.type),
      attrs: item.attrs,
      ports: item.ports,
      custom: true,
    })
    groups.set(category, bucket)
  }
  return [...groups.entries()].map(([category, items]) => ({ category, items }))
}

export function filterGroups(groups: TemplateGroup[], query: string): TemplateGroup[] {
  const normalized = query.trim().toLowerCase()
  if (!normalized) return groups
  return groups
    .map(group => ({
      category: group.category,
      items: group.items.filter(
        template =>
          template.label.toLowerCase().includes(normalized) ||
          template.name.toLowerCase().includes(normalized) ||
          template.type.toLowerCase().includes(normalized) ||
          group.category.toLowerCase().includes(normalized),
      ),
    }))
    .filter(group => group.items.length > 0)
}
