"""Load the land cover / land use hierarchies and the editable label hints.

The CSVs have one row per leaf with Level_1/2/3 code + description columns.
Rows whose Level_3 code equals the Level_2 code (e.g. C10/C10) have no real
third level, so no Level 3 node is created for them.

`label_hints.csv` holds what the model actually sees for each class: the
label name, an optional hint (description), and whether the class is enabled.
It is created from the taxonomy CSVs on first use and can be edited in the UI.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import pandas as pd

from .config import LABEL_HINTS_FILE, TAXONOMIES

# Hints for the top level. Soil-science abstracts mention "soil" everywhere, so
# hints avoid generic words like "soil" that would make every class fire.
DEFAULT_HINTS = {
    ("landcover", "A"): "built-up and sealed surfaces: buildings, settlements, cities, roads, railways, industrial sites, greenhouses",
    ("landcover", "B"): "agricultural fields with crops: arable land, cereals, maize, vegetables, fodder crops, orchards, vineyards, olive groves",
    ("landcover", "C"): "forest and woodland: broadleaved, coniferous or mixed tree stands",
    ("landcover", "D"): "shrubs and scrub vegetation: heathland, maquis, garrigue, bushland",
    ("landcover", "E"): "grass-dominated vegetation: pastures, meadows, rangelands, grazed grassland, steppe, savanna",
    ("landcover", "F"): "land without vegetation: bare rock, scree, sand dunes, beaches, deserts, lichens and moss",
    ("landcover", "G"): "open water: rivers, streams, lakes, reservoirs, estuaries, lagoons, sea and ocean",
    ("landcover", "H"): "wetlands: marshes, fens, peatlands, bogs, salt marshes, intertidal mudflats, salines",
    ("landuse", "U1"): "production from land: agriculture, farming, livestock grazing, forestry, timber, fishing, aquaculture, mining and quarrying",
    ("landuse", "U2"): "industry: energy production, power plants, manufacturing, industrial facilities",
    ("landuse", "U3"): "services and infrastructure: transport, utilities, water and waste treatment, construction, commerce, community services, recreation, residential and urban areas",
    ("landuse", "U4"): "land not in use: abandoned farmland, abandoned industrial or residential sites, natural or semi-natural areas without economic use",
}

# Photo-interpretation-only classes can't be recognised from text.
DEFAULT_DISABLED = {("landcover", "Bx0"), ("landcover", "Bx1"), ("landcover", "Bx2")}

HINT_COLUMNS = ["taxonomy", "code", "level", "parent_code", "name", "hint", "enabled"]

_RESERVED = ("[P]", "[L]", "[C]", "[E]", "[R]", "[DESCRIPTION]", "[EXAMPLE]", "[OUTPUT]")


def clean_label(text: str) -> str:
    """Make a string safe for GLiNER2 prompts: parentheses and marker tokens are reserved."""
    text = re.sub(r"\s*\(([^)]*)\)", r", \1", str(text))
    text = text.replace("(", " ").replace(")", " ")
    for token in _RESERVED:
        text = text.replace(token, " ")
    return re.sub(r"\s+", " ", text).strip(" ,")


@dataclass
class Node:
    taxonomy: str
    code: str
    level: int
    name: str
    parent: str | None
    hint: str = ""
    enabled: bool = True
    children: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        return clean_label(self.name)


@dataclass
class Taxonomy:
    key: str
    name: str
    instruction: str
    nodes: dict[str, Node]

    def roots(self) -> list[Node]:
        return [n for n in self.nodes.values() if n.level == 1 and n.enabled]

    def children(self, code: str) -> list[Node]:
        return [self.nodes[c] for c in self.nodes[code].children if self.nodes[c].enabled]

    def description(self, node: Node) -> str | None:
        """Hint if set, otherwise a list of the node's sub-classes."""
        if node.hint and node.hint.strip():
            return clean_label(node.hint)
        kids = self.children(node.code)
        if kids:
            return clean_label("includes " + ", ".join(k.name for k in kids))
        return None

    def label_map(self, nodes: list[Node]) -> dict[str, str]:
        """Model label text -> code, de-duplicated among siblings."""
        out: dict[str, str] = {}
        for n in nodes:
            label = n.label
            if label in out:
                label = f"{label} {n.code}"
            out[label] = n.code
        return out


def _nodes_from_csv(key: str) -> list[dict]:
    df = pd.read_csv(TAXONOMIES[key]["csv"], dtype=str).fillna("")
    rows: dict[str, dict] = {}
    for r in df.itertuples(index=False):
        levels = [
            (1, r.Level_1_Code, r.Level_1_Description, None),
            (2, r.Level_2_Code, r.Level_2_Description, r.Level_1_Code),
            (3, r.Level_3_Code, r.Level_3_Description, r.Level_2_Code),
        ]
        for level, code, name, parent in levels:
            code = code.strip()
            if not code or code in rows:
                continue  # also skips L3 rows that repeat the L2 code
            rows[code] = {
                "taxonomy": key,
                "code": code,
                "level": level,
                "parent_code": parent or "",
                "name": name.strip(),
                "hint": DEFAULT_HINTS.get((key, code), ""),
                "enabled": (key, code) not in DEFAULT_DISABLED,
            }
    return list(rows.values())


def default_hints() -> pd.DataFrame:
    rows = [row for key in TAXONOMIES for row in _nodes_from_csv(key)]
    return pd.DataFrame(rows, columns=HINT_COLUMNS)


def load_hints(path=None) -> pd.DataFrame:
    if path is None:
        path = LABEL_HINTS_FILE
        if not path.exists():
            save_hints(default_hints())
    df = pd.read_csv(path, dtype={"code": str, "parent_code": str, "hint": str, "name": str})
    df["hint"] = df["hint"].fillna("")
    df["parent_code"] = df["parent_code"].fillna("")
    df["enabled"] = df["enabled"].astype(str).str.lower().isin(["true", "1", "yes"])
    df["level"] = df["level"].astype(int)
    return df[HINT_COLUMNS]


def save_hints(df: pd.DataFrame) -> None:
    df[HINT_COLUMNS].to_csv(LABEL_HINTS_FILE, index=False)


def build_taxonomy(key: str, hints: pd.DataFrame | None = None) -> Taxonomy:
    hints = load_hints() if hints is None else hints
    nodes: dict[str, Node] = {}
    for r in hints[hints["taxonomy"] == key].itertuples(index=False):
        nodes[r.code] = Node(
            taxonomy=key, code=r.code, level=int(r.level), name=r.name,
            parent=r.parent_code or None, hint=r.hint or "", enabled=bool(r.enabled),
        )
    for n in nodes.values():
        if n.parent and n.parent in nodes:
            nodes[n.parent].children.append(n.code)
    meta = TAXONOMIES[key]
    return Taxonomy(key=key, name=meta["name"], instruction=meta["instruction"], nodes=nodes)
