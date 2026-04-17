from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime
import uuid


def short_id():
    return uuid.uuid4().hex[:8]


@dataclass
class Node:
    id: str = field(default_factory=short_id)
    label: str = ""
    description: str = ""
    type: str = "state"  # state|event|decision|concept|question|blackbox|goal|task|asset|gate
    archetype: Optional[str] = None  # root_cause|mechanism|effect|moderator|evidence|question
    tags: list = field(default_factory=list)
    confidence: float = 0.7
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    source: str = "user"  # user|llm|import
    deprecated: bool = False
    flagged: bool = False
    chain_link: Optional[str] = None  # filename of linked chain, e.g. "sleep-cognition.causal.json"


@dataclass
class Edge:
    id: str = field(default_factory=short_id)
    from_id: str = ""
    to_id: str = ""
    relation: str = "CAUSES"
    weight: float = 0.5
    confidence: float = 0.5
    direction: str = "forward"
    condition: Optional[str] = None
    evidence: str = ""
    deprecated: bool = False
    flagged: bool = False
    version: int = 1
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    source: str = "user"


@dataclass
class ChainMeta:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = "Untitled Chain"
    domain: str = "custom"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    version: int = 1
    author: str = ""
    description: str = ""


@dataclass
class CausalChain:
    meta: ChainMeta = field(default_factory=ChainMeta)
    nodes: list = field(default_factory=list)
    edges: list = field(default_factory=list)
    history: list = field(default_factory=list)
    summaries: list = field(default_factory=list)
