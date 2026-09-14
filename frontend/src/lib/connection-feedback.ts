import { LiteGraph, type LGraphCanvas, type LGraphNode } from 'litegraph.js'

type TargetNode = LGraphNode & {
  simulanka?: unknown
  simulankaConnectionRejection?: (
    source: LGraphNode, outputIndex: number, inputIndex: number,
  ) => string | null
}
type FeedbackCanvas = Omit<LGraphCanvas, 'isOverNodeInput'> & {
  graph_mouse: [number, number]
  isOverNodeInput: (node: LGraphNode, x: number, y: number, pos?: [number, number]) => number
  connecting_node: TargetNode | null
  connecting_output: LGraphNode['outputs'][number] | null
  connecting_input: LGraphNode['inputs'][number] | null
  connecting_pos: [number, number] | Float32Array | null
  connecting_slot: number
  _highlight_input: number[] | null
  _highlight_input_slot: LGraphNode['inputs'][number] | null
  _highlight_output: number[] | null
  isOverNodeBox: (node: LGraphNode, x: number, y: number) => boolean
}

const nativeTypes = LiteGraph as unknown as {
  isValidConnection: (a: unknown, b: unknown) => boolean
}
const installed = new WeakSet<LGraphCanvas>()
const REJECTED_PORT_COLOR = '#a45b62'

/** LiteGraph 0.7.18 has no eligibility hook in its drag-target renderer. */
export function installConnectionFeedback(canvas: LGraphCanvas): void {
  if (installed.has(canvas)) return
  installed.add(canvas)
  const c = canvas as unknown as FeedbackCanvas
  const drawFront = c.drawFrontCanvas.bind(c)
  const drawNode = c.drawNode.bind(c)

  function source(): TargetNode | null {
    const node = c.connecting_node
    return node?.simulanka && c.connecting_output
      && node.outputs[c.connecting_slot] === c.connecting_output
      && c.graph?.getNodeById(node.id) === node ? node : null
  }

  c.drawFrontCanvas = () => {
    // 0.7.18 clear()/setGraph() clears connecting_node but leaves the other
    // drag fields behind; its next frame otherwise dereferences a null node.
    if (!c.connecting_node) {
      c.connecting_output = null
      c.connecting_input = null
      c.connecting_pos = null
      c.connecting_slot = -1
      c._highlight_output = null
    }
    const output = source()
    if (output) {
      // Use the same node/slot hit tests as processMouseMove. Never return -1
      // from isOverNodeInput: processMouseUp would then auto-connect by type.
      c._highlight_input = null
      c._highlight_input_slot = null
      const [x, y] = c.graph_mouse
      const node = c.graph.getNodeOnPos(x, y, c.visible_nodes) as TargetNode | null
      if (node && !c.isOverNodeBox(node, x, y)) {
        const pos: [number, number] = [0, 0]
        const index = c.isOverNodeInput(node, x, y, pos)
        const slot = node.inputs?.[index]
        const rejected = slot && node.simulankaConnectionRejection?.(output, c.connecting_slot, index)
        if (slot && !rejected && nativeTypes.isValidConnection(c.connecting_output!.type, slot.type)) {
          c._highlight_input = pos
          c._highlight_input_slot = slot
        }
      }
    } else if (!c.connecting_node || c.connecting_node.simulanka) {
      c._highlight_input = null
      c._highlight_input_slot = null
    }
    drawFront()
  }

  c.drawNode = (node, ctx) => {
    const output = source()
    const target = node as TargetNode
    if (!output || !target.simulankaConnectionRejection || !node.inputs?.length) return drawNode(node, ctx)
    const colors = node.inputs.map(slot => ({
      on: Object.getOwnPropertyDescriptor(slot, 'color_on'),
      off: Object.getOwnPropertyDescriptor(slot, 'color_off'),
    }))
    try {
      node.inputs.forEach((slot, index) => {
        if (target.simulankaConnectionRejection!(output, c.connecting_slot, index)) {
          slot.color_on = REJECTED_PORT_COLOR
          slot.color_off = REJECTED_PORT_COLOR
        }
      })
      // Native rendering still owns every handle, label, shape and anchor.
      drawNode(node, ctx)
    } finally {
      node.inputs.forEach((slot, index) => {
        const { on, off } = colors[index]
        if (on) Object.defineProperty(slot, 'color_on', on)
        else delete slot.color_on
        if (off) Object.defineProperty(slot, 'color_off', off)
        else delete slot.color_off
      })
    }
  }
}
