from __future__ import annotations
from dataclasses import dataclass
from copy import deepcopy


@dataclass(frozen=True, eq=False)
class SourceElement:
    id: str
    document_id: str
    parse_id: str
    text: str
    _regions: list
    context: str

    def __post_init__(self):
        object.__setattr__(self, '_regions', deepcopy(self._regions))

    @property
    def regions(self):
        return deepcopy(self._regions)

    def to_record(self):
        return {'id': self.id, 'document_id': self.document_id, 'parse_id': self.parse_id,
                'text': self.text, 'regions': deepcopy(self._regions), 'context': self.context}
