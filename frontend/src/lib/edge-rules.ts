import type {
  EdgeProfileDescriptorDTO,
  NodeDTO,
  PortDTO,
  RegistryDescriptorDTO,
} from './types'

const ANY_PROFILE = '*'

function canonicalNodeProfile(descriptor: RegistryDescriptorDTO, key: string): string {
  return descriptor.aliases.node[key] ?? key
}

function canonicalPortType(descriptor: RegistryDescriptorDTO, key: string): string {
  return descriptor.aliases.port[key] ?? key
}

function endpointRejection(
  edge: EdgeProfileDescriptorDTO,
  node: NodeDTO,
  allowedProfiles: readonly string[],
  requiredCapabilities: readonly string[],
  side: 'source' | 'target',
  descriptor: RegistryDescriptorDTO,
): string | null {
  if (node.unknown_profile) return `${side} 使用未知 Profile: ${node.type}`
  const profile = canonicalNodeProfile(descriptor, node.type)
  if (!allowedProfiles.includes(ANY_PROFILE) && !allowedProfiles.includes(profile)) {
    return `${edge.key} 不接受 ${side} Profile: ${profile}`
  }
  const missing = requiredCapabilities.filter(item => !node.capabilities.includes(item))
  if (missing.length > 0) {
    return `${side} Profile 缺少 capability: ${missing.join(', ')}`
  }
  return null
}

/**
 * Return a visible reason when the descriptor rules reject a proposed edge.
 * null means "eligible for a server attempt", never "guaranteed writable".
 */
export function edgeConnectionRejection(
  descriptor: RegistryDescriptorDTO | null,
  edgeKey: string,
  sourceNode: NodeDTO,
  targetNode: NodeDTO,
  sourcePort: PortDTO,
  targetPort: PortDTO,
): string | null {
  if (!descriptor) return null
  const canonicalEdge = descriptor.aliases.edge[edgeKey] ?? edgeKey
  const edge = descriptor.edge_profiles.find(item => item.key === canonicalEdge)
  if (!edge) return `Registry 未注册 Edge Profile: ${edgeKey}`
  if (!edge.needs_ports) return `${edge.key} 不使用端口，不能通过拖线创建`

  const sourceType = canonicalPortType(descriptor, sourcePort.port_type)
  const targetType = canonicalPortType(descriptor, targetPort.port_type)
  if (sourcePort.unknown_profile || !descriptor.port_types.includes(sourceType)) {
    return `source 使用未知 Port type: ${sourcePort.port_type}`
  }
  if (targetPort.unknown_profile || !descriptor.port_types.includes(targetType)) {
    return `target 使用未知 Port type: ${targetPort.port_type}`
  }
  if (edge.source_port_direction && sourcePort.side !== edge.source_port_direction) {
    return `${edge.key} source 端口必须为 ${edge.source_port_direction}`
  }
  if (edge.target_port_direction && targetPort.side !== edge.target_port_direction) {
    return `${edge.key} target 端口必须为 ${edge.target_port_direction}`
  }

  return endpointRejection(
    edge,
    sourceNode,
    edge.source_profiles,
    edge.source_capabilities,
    'source',
    descriptor,
  ) ?? endpointRejection(
    edge,
    targetNode,
    edge.target_profiles,
    edge.target_capabilities,
    'target',
    descriptor,
  )
}
