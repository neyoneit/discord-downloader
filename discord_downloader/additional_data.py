import uuid
from typing import NamedTuple, Optional


class AdditionalData(NamedTuple):
    in_channel: str
    message_id: Optional[int]
    title: Optional[str]
    description: Optional[str]
    rerendering_round: Optional[int]
    url: Optional[str]
    has_unknown: bool
    filename: str

    @staticmethod
    def reconstruct(additional_data_raw):
        if isinstance(additional_data_raw, list):
            [in_channel, message_id, *rest] = additional_data_raw
            if len(rest) == 0:
                title = None
                description = None
                rerendering_round = None
                url = None
                has_unknown = False
                filename = uuid.uuid4().hex
            else:
                [title, description, rerendering_round, url, *rest2] = rest
                if len(rest2) == 0:
                    has_unknown = False
                    filename = uuid.uuid4().hex
                else:
                    [has_unknown, filename, *rest3] = rest2
            return AdditionalData(in_channel=in_channel, message_id=message_id, title=title, description=description,
                                  rerendering_round=rerendering_round, url=url, has_unknown=has_unknown,
                                  filename=filename)
        else:
            return AdditionalData(in_channel=additional_data_raw, message_id=None, title=None, description=None,
                                  rerendering_round=None, url=None, has_unknown=False, filename=uuid.uuid4().hex)

    def serialize(self):
        return [self.in_channel, self.message_id, self.title, self.description, self.rerendering_round, self.url,
                self.has_unknown, self.filename]
