// Add-node catalog: curated torch building blocks, grouped by category, plus
// the user's custom templates fetched from the server (/ui/templates).
//
// A hand-placed node is the same species as an imported one: type="module"
// with the importer's attr convention (class_name / class_module), so cards,
// inspector and future trust colouring read both identically. What the hand
// cannot claim is observation — no shapes, no confidence on ports (§13.3.1
// honest labelling: the muted default dot is correct for a sketch).

export interface TemplatePort {
  name: string
  direction: 'in' | 'out'
  port_type?: string
}

export interface NodeTemplate {
  label: string // menu label, e.g. "Conv2d"
  name: string // default node name, e.g. "conv2d" (server suffixes collisions)
  category: string
  type: string // graph node type
  attrs: Record<string, unknown>
  ports: TemplatePort[]
  custom?: boolean // true = stored on the server, deletable from the menu
}

export interface TemplateGroup {
  category: string
  items: NodeTemplate[]
}

const IO: TemplatePort[] = [
  { name: 'input', direction: 'in', port_type: 'tensor' },
  { name: 'output', direction: 'out', port_type: 'tensor' },
]

// One torch.nn module entry. Default ports are the single-stream input/output
// pair; multi-input modules pass their own.
function nn(category: string, className: string, ports: TemplatePort[] = IO): NodeTemplate {
  return {
    label: className,
    name: className.toLowerCase(),
    category,
    type: 'module',
    attrs: { class_name: className, class_module: 'torch.nn' },
    ports,
  }
}

// A bare torch op (torch.cat, torch.matmul …) — not an nn.Module, but as a
// hand-sketched dataflow step it is still a module-typed node; class_module
// records where the op actually lives.
function op(className: string, ports: TemplatePort[]): NodeTemplate {
  return {
    label: className,
    name: className.toLowerCase(),
    category: '张量运算',
    type: 'module',
    attrs: { class_name: className, class_module: 'torch' },
    ports,
  }
}

const ins = (...names: string[]): TemplatePort[] => [
  ...names.map((n): TemplatePort => ({ name: n, direction: 'in', port_type: 'tensor' })),
  { name: 'output', direction: 'out', port_type: 'tensor' },
]

export const TORCH_CATALOG: NodeTemplate[] = [
  // 卷积
  nn('卷积', 'Conv1d'),
  nn('卷积', 'Conv2d'),
  nn('卷积', 'Conv3d'),
  nn('卷积', 'ConvTranspose2d'),
  // 线性
  nn('线性', 'Linear'),
  nn('线性', 'Bilinear', ins('input1', 'input2')),
  nn('线性', 'Embedding', [
    { name: 'indices', direction: 'in', port_type: 'tensor' },
    { name: 'output', direction: 'out', port_type: 'tensor' },
  ]),
  // 归一化
  nn('归一化', 'BatchNorm1d'),
  nn('归一化', 'BatchNorm2d'),
  nn('归一化', 'LayerNorm'),
  nn('归一化', 'GroupNorm'),
  nn('归一化', 'RMSNorm'),
  // 激活
  nn('激活', 'ReLU'),
  nn('激活', 'GELU'),
  nn('激活', 'SiLU'),
  nn('激活', 'LeakyReLU'),
  nn('激活', 'Sigmoid'),
  nn('激活', 'Tanh'),
  nn('激活', 'Softmax'),
  // 池化
  nn('池化', 'MaxPool2d'),
  nn('池化', 'AvgPool2d'),
  nn('池化', 'AdaptiveAvgPool2d'),
  // 正则
  nn('正则', 'Dropout'),
  nn('正则', 'Dropout2d'),
  // 注意力 / Transformer
  nn('注意力', 'MultiheadAttention', ins('query', 'key', 'value')),
  nn('注意力', 'TransformerEncoderLayer'),
  nn('注意力', 'TransformerDecoderLayer', ins('tgt', 'memory')),
  // 循环
  nn('循环', 'RNN'),
  nn('循环', 'LSTM'),
  nn('循环', 'GRU'),
  // 损失
  nn('损失', 'CrossEntropyLoss', ins('input', 'target')),
  nn('损失', 'MSELoss', ins('input', 'target')),
  nn('损失', 'BCEWithLogitsLoss', ins('input', 'target')),
  nn('损失', 'L1Loss', ins('input', 'target')),
  // 形状
  nn('形状', 'Flatten'),
  nn('形状', 'Unflatten'),
  op('reshape', ins('input')),
  op('permute', ins('input')),
  // 张量运算
  op('cat', ins('a', 'b')),
  op('stack', ins('a', 'b')),
  op('add', ins('a', 'b')),
  op('mul', ins('a', 'b')),
  op('matmul', ins('a', 'b')),
  op('mean', ins('input')),
  op('sum', ins('input')),
  // 通用
  {
    label: '空白节点',
    name: 'node',
    category: '通用',
    type: 'module',
    attrs: {},
    ports: IO,
  },
  {
    label: '空容器',
    name: 'container',
    category: '通用',
    type: 'module',
    attrs: {},
    ports: [],
  },
  {
    label: 'Model 容器',
    name: 'model',
    category: '通用',
    type: 'model',
    attrs: {},
    ports: [],
  },
  {
    label: '目录',
    name: 'dir',
    category: '通用',
    type: 'directory',
    attrs: {},
    ports: [],
  },
]

// Frontend mirror of the kernel containment matrix (registry/builtin.py
// NODE_TYPES.allow_parents) for the types the menu can place. The kernel 422
// stays the hard gate — this only keeps the menu from offering forty entries
// that would all be refused in the current container. null = top-level.
const ALLOW_PARENTS: Record<string, (string | null)[]> = {
  module: ['model', 'module'],
  model: ['directory'],
  directory: ['directory', null],
}

function placeableIn(type: string, parentType: string | null): boolean {
  const allowed = ALLOW_PARENTS[type]
  // Unknown type (e.g. a hand-edited custom template): offer it and let the
  // kernel adjudicate — hiding it would just be a silent lie.
  if (!allowed) return true
  return allowed.includes(parentType)
}

// Merge built-ins with the server's custom templates into ordered groups,
// keeping only what the kernel would accept inside the current container
// (parentType = root_info.type of the active view; null at top-level).
// Custom categories come after the built-in ones; "custom" (the server
// default) displays as 我的模板.
export function buildGroups(
  custom: Record<
    string,
    { category: string; type: string; attrs: Record<string, unknown>; ports: TemplatePort[] }
  >,
  parentType: string | null,
): TemplateGroup[] {
  const groups = new Map<string, NodeTemplate[]>()
  for (const t of TORCH_CATALOG) {
    if (!placeableIn(t.type, parentType)) continue
    const bucket = groups.get(t.category) ?? []
    bucket.push(t)
    groups.set(t.category, bucket)
  }
  for (const [name, t] of Object.entries(custom)) {
    if (!placeableIn(t.type, parentType)) continue
    const category = t.category === 'custom' ? '我的模板' : t.category
    const bucket = groups.get(category) ?? []
    bucket.push({
      label: name,
      name,
      category,
      type: t.type,
      attrs: t.attrs,
      ports: t.ports,
      custom: true,
    })
    groups.set(category, bucket)
  }
  return [...groups.entries()].map(([category, items]) => ({ category, items }))
}

// Case-insensitive filter over label + category; empty query = everything.
export function filterGroups(groups: TemplateGroup[], query: string): TemplateGroup[] {
  const q = query.trim().toLowerCase()
  if (!q) return groups
  return groups
    .map(g => ({
      category: g.category,
      items: g.items.filter(
        t =>
          t.label.toLowerCase().includes(q) ||
          t.name.toLowerCase().includes(q) ||
          g.category.toLowerCase().includes(q),
      ),
    }))
    .filter(g => g.items.length > 0)
}
