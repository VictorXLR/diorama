from typing import Any, Dict, List

from diorama.models.context import ContextVisualization, NodeCategory

NODE_COLORS: Dict[str, Dict[str, str]] = {
    "client": {"bg": "#e0e7ff", "stroke": "#4338ca"},
    "service": {"bg": "#e0f2fe", "stroke": "#0369a1"},
    "gateway": {"bg": "#f3e8ff", "stroke": "#7e22ce"},
    "database": {"bg": "#fef3c7", "stroke": "#b45309"},
    "queue": {"bg": "#ffedd5", "stroke": "#c2410c"},
    "storage": {"bg": "#ecfdf5", "stroke": "#047857"},
    "external": {"bg": "#f1f5f9", "stroke": "#475569"},
    "workflow_step": {"bg": "#fce7f3", "stroke": "#be185d"},
    "concept": {"bg": "#fef9c3", "stroke": "#a16207"},
    "custom": {"bg": "#f8fafc", "stroke": "#334155"},
}

def generate_context_whiteboard_skeletons(context: ContextVisualization) -> List[Dict[str, Any]]:
    """
    Generates Excalidraw skeleton elements from a generalized ContextVisualization.
    Positions top-level architectures, system components, workflows, and connections.
    """
    skeletons: List[Dict[str, Any]] = []

    start_x = 80
    start_y = 60
    col_width = 320
    col_gap = 50
    node_height = 100
    node_gap = 35

    # Group nodes by group_id
    groups = list(context.groups)
    node_to_group: Dict[str, str] = {}
    grouped_nodes: Dict[str, List[Any]] = {}

    for g in groups:
        grouped_nodes[g.id] = []

    ungrouped_nodes = []
    for node in context.nodes:
        if node.group_id and node.group_id in grouped_nodes:
            grouped_nodes[node.group_id].append(node)
            node_to_group[node.id] = node.group_id
        else:
            ungrouped_nodes.append(node)

    # If there are ungrouped nodes and existing groups, create an implicit group
    if ungrouped_nodes:
        if groups:
            default_gid = "group-general"
            from diorama.models.context import ContextGroup
            groups.append(ContextGroup(id=default_gid, title="Core Services & Components", description="General subsystem"))
            grouped_nodes[default_gid] = ungrouped_nodes
        else:
            # No groups defined at all: create pseudo-columns
            # Distribute nodes across 2-3 columns
            cols_count = max(1, min(3, (len(context.nodes) + 2) // 3))
            from diorama.models.context import ContextGroup
            for i in range(cols_count):
                gid = f"col-{i + 1}"
                groups.append(ContextGroup(id=gid, title=f"Tier {i + 1}", description=None))
                grouped_nodes[gid] = []
            for i, node in enumerate(context.nodes):
                gid = f"col-{(i % cols_count) + 1}"
                grouped_nodes[gid].append(node)

    num_cols = max(1, len(groups))
    total_width = max(980, num_cols * (col_width + col_gap) + 380)

    # 1. Header Banner
    skeletons.append({
        "type": "rectangle",
        "x": start_x,
        "y": start_y,
        "width": total_width,
        "height": 115,
        "backgroundColor": "#0f172a",
        "strokeColor": "#1e293b",
        "fillStyle": "solid",
        "roundness": {"type": 3},
        "roughness": 0,
        "label": {
            "text": f"[{context.diagram_type.upper().replace('_', ' ')}] {context.title.upper()}\n{context.summary}",
            "fontSize": 18,
            "textAlign": "left",
            "verticalAlign": "middle",
        },
    })

    # Track node bounds for connection arrows: node_id -> (x, y, w, h)
    node_bounds: Dict[str, Dict[str, float]] = {}
    max_column_bottom = start_y + 140

    for col_idx, group in enumerate(groups):
        col_x = start_x + col_idx * (col_width + col_gap)
        group_nodes = grouped_nodes.get(group.id, [])
        col_y = start_y + 145

        # Measure column height for boundary container
        inner_content_height = max(160, 50 + len(group_nodes) * (node_height + node_gap))

        # Group Boundary Container
        skeletons.append({
            "type": "rectangle",
            "x": col_x - 12,
            "y": col_y,
            "width": col_width + 24,
            "height": inner_content_height + 20,
            "backgroundColor": group.color or "#f8fafc",
            "strokeColor": "#94a3b8",
            "strokeStyle": "dashed",
            "fillStyle": "solid",
            "roundness": {"type": 3},
            "roughness": 0,
            "strokeWidth": 1.5,
            "opacity": 80,
        })

        # Group Header Label
        group_header_text = group.title.upper()
        if group.description:
            group_header_text += f"\n{group.description}"

        skeletons.append({
            "type": "text",
            "x": col_x,
            "y": col_y + 12,
            "text": group_header_text,
            "fontSize": 14,
            "textAlign": "left",
            "verticalAlign": "top",
            "strokeColor": "#334155",
        })

        curr_y = col_y + 55

        for node in group_nodes:
            colors = NODE_COLORS.get(node.category, {"bg": "#f8fafc", "stroke": "#475569"})

            # Node card text
            header_line = f"[{node.category.upper()}] {node.label}"
            sub_line = node.subtitle or ""
            desc_line = node.description or ""
            tags_line = f"Tags: {', '.join(node.tags)}" if node.tags else ""
            status_line = f"Status: {node.status}" if node.status else ""

            details = [line for line in [sub_line, desc_line, status_line, tags_line] if line]
            card_text = header_line
            if details:
                card_text += "\n" + "\n".join(details)

            skeletons.append({
                "type": "rectangle",
                "x": col_x,
                "y": curr_y,
                "width": col_width,
                "height": node_height,
                "backgroundColor": colors["bg"],
                "strokeColor": colors["stroke"],
                "fillStyle": "solid",
                "roundness": {"type": 3},
                "roughness": 1,
                "strokeWidth": 2,
                "label": {
                    "text": card_text,
                    "fontSize": 13,
                    "textAlign": "left",
                    "verticalAlign": "middle",
                },
            })

            node_bounds[node.id] = {
                "x": col_x,
                "y": curr_y,
                "w": col_width,
                "h": node_height,
            }

            curr_y += node_height + node_gap

        if curr_y > max_column_bottom:
            max_column_bottom = curr_y

    # 3. Connections between nodes
    for conn in context.connections:
        from_b = node_bounds.get(conn.from_node)
        to_b = node_bounds.get(conn.to_node)
        if not from_b or not to_b:
            continue

        # Calculate start and end anchor points
        from_cx = from_b["x"] + from_b["w"] / 2
        from_cy = from_b["y"] + from_b["h"] / 2
        to_cx = to_b["x"] + to_b["w"] / 2
        to_cy = to_b["y"] + to_b["h"] / 2

        # Connect right-to-left if from is to the left of to, or top-to-bottom
        if abs(to_cx - from_cx) > abs(to_cy - from_cy):
            if to_cx > from_cx:
                start_pt = (from_b["x"] + from_b["w"], from_cy)
                end_pt = (to_b["x"], to_cy)
            else:
                start_pt = (from_b["x"], from_cy)
                end_pt = (to_b["x"] + to_b["w"], to_cy)
        else:
            if to_cy > from_cy:
                start_pt = (from_cx, from_b["y"] + from_b["h"])
                end_pt = (to_cx, to_b["y"])
            else:
                start_pt = (from_cx, from_b["y"])
                end_pt = (to_cx, to_b["y"] + to_b["h"])

        dx = end_pt[0] - start_pt[0]
        dy = end_pt[1] - start_pt[1]

        arrow_elem: Dict[str, Any] = {
            "type": "arrow",
            "x": start_pt[0],
            "y": start_pt[1],
            "points": [
                [0, 0],
                [dx, dy],
            ],
            "strokeColor": "#6366f1",
            "strokeWidth": 2,
            "strokeStyle": conn.style,
            "roundness": {"type": 2},
        }

        if conn.label:
            arrow_elem["label"] = {
                "text": conn.label,
                "fontSize": 12,
                "textAlign": "center",
                "verticalAlign": "middle",
            }

        skeletons.append(arrow_elem)

    # 4. Side Panels / Insights Cards
    side_x = start_x + num_cols * (col_width + col_gap) + 20
    side_y = start_y + 145

    if context.insights:
        for insight in context.insights:
            insight_bg = "#f0fdf4" if insight.kind == "decision" else ("#fffbeb" if insight.kind == "warning" else "#f8fafc")
            insight_stroke = "#16a34a" if insight.kind == "decision" else ("#d97706" if insight.kind == "warning" else "#64748b")

            skeletons.append({
                "type": "rectangle",
                "x": side_x,
                "y": side_y,
                "width": 320,
                "height": 130,
                "backgroundColor": insight_bg,
                "strokeColor": insight_stroke,
                "fillStyle": "solid",
                "roundness": {"type": 3},
                "roughness": 1,
                "strokeWidth": 1.5,
                "label": {
                    "text": f"[{insight.kind.upper()}] {insight.title}\n\n{insight.content}",
                    "fontSize": 12,
                    "textAlign": "left",
                    "verticalAlign": "middle",
                },
            })
            side_y += 145

    # 5. Top-Level Context Stats & Metrics Widget (drawn on Excalidraw canvas)
    skeletons.append({
        "type": "rectangle",
        "x": side_x,
        "y": side_y,
        "width": 320,
        "height": 150,
        "backgroundColor": "#f8fafc",
        "strokeColor": "#475569",
        "fillStyle": "solid",
        "roundness": {"type": 3},
        "roughness": 1,
        "strokeWidth": 1.5,
        "label": {
            "text": (
                f"DIORAMA VISUAL CONTEXT WIDGET\n\n"
                f"• Diagram Type: {context.diagram_type}\n"
                f"• Active Nodes: {len(context.nodes)}\n"
                f"• Connections: {len(context.connections)}\n"
                f"• Domain Groups: {len(context.groups)}\n\n"
                "Tip: Ask AI to add components, connect services, or re-structure architecture."
            ),
            "fontSize": 12,
            "textAlign": "left",
            "verticalAlign": "middle",
        },
    })
    side_y += 165

    # 6. Live AI Agent & Model Status Widget (drawn on Excalidraw canvas)
    model_name = "OpenRouter"
    skeletons.append({
        "type": "rectangle",
        "x": side_x,
        "y": side_y,
        "width": 320,
        "height": 110,
        "backgroundColor": "#0f172a",
        "strokeColor": "#38bdf8",
        "fillStyle": "solid",
        "roundness": {"type": 3},
        "roughness": 0,
        "strokeWidth": 1.5,
        "label": {
            "text": (
                f"AGENT WIDGET: ACTIVE\n\n"
                f"• Engine: {model_name}\n"
                f"• Stream: WebSocket Realtime Sync\n"
                f"• Mode: Context & Visual Graph Synthesis"
            ),
            "fontSize": 12,
            "textAlign": "left",
            "verticalAlign": "middle",
        },
    })

    for index, element in enumerate(skeletons):
        element["id"] = f"{context.id}-preset-{index}"
    return skeletons
