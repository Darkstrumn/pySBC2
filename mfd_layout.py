"""Render the MFD's local HTML subset through Pygame drawing primitives."""

from xml.etree import ElementTree


class MFDLayout:
    def __init__(self, path):
        root = ElementTree.parse(path).getroot()
        self.header = root.find("header")
        self.pages = {node.attrib["id"]: node for node in root.findall("section")}

    def draw(self, panel, element, values, widgets):
        tag, attrs = element.tag, element.attrib
        if "data-rect" in attrs:
            rect = tuple(map(int, attrs["data-rect"].split(",")))
            if tag == "button":
                page = attrs["data-action"]
                selected = panel.tab == page or page == "settings" and panel.tab != "main"
                panel._button(element.text.strip(), rect, lambda: panel._open_page(page), selected)
            elif tag == "div":
                panel._box(rect)
                if "data-widget" in attrs:
                    widgets[attrs["data-widget"]](rect)
        elif tag == "span":
            x, y = map(int, attrs["data-pos"].split(","))
            style = attrs.get("data-style")
            label = values.get(attrs["data-value"], "") if "data-value" in attrs else element.text
            panel._text(label or "", x, y, panel.font_title if style == "title" else None,
                        panel.accent if style == "accent" else panel.dim if style == "dim" else None)
        for child in element:
            self.draw(panel, child, values, widgets)
