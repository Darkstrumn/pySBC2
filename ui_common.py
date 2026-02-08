"""Shared UI formatting helpers used by multiple UI backends."""


def build_dashboard(state, sbc):
    """Build normalized dashboard text rows from current parsed controller state."""
    return {
        "title": "STEEL BATTALION CONTROLLER",
        "lines": [
            f"Aim X: {state['aim_x']:>4}   Aim Y: {state['aim_y']:>4}",
            f"Sight X: {state['sight_x']:>4}  Sight Y: {state['sight_y']:>4}",
            f"Rotation: {state['rotation']:>5}",
            f"Pedals L:{state['left_pedal']:>4}  M:{state['middle_pedal']:>4}  R:{state['right_pedal']:>4}",
            f"Tuner: {state['tuner']:>2}   Gear: {gear_label(state['gear'])}",
        ],
        "pressed": [name for i, name in enumerate(sbc.button_names) if state["buttons"][i]],
    }


def gear_label(value):
    """Render controller gear value as user-facing label."""
    if value == -2:
        return "R"
    if value == -1:
        return "N"
    if value in (1, 2, 3, 4, 5):
        return str(value)
    return str(value)
