from typing import NamedTuple, Optional


class AdditionalData(NamedTuple):
    in_channel: str
    message_id: Optional[int]
    title: Optional[str]
    description: Optional[str]
    rerendering_round: Optional[int]
    url: Optional[str]

    @staticmethod
    def reconstruct(additional_data_raw):
        if isinstance(additional_data_raw, list):
            [in_channel, message_id, *rest] = additional_data_raw
            if len(rest) == 0:
                title = None
                description = None
                rerendering_round = None
                url = None
            else:
                [title, description, rerendering_round, url] = rest
            return AdditionalData(in_channel=in_channel, message_id=message_id, title=title, description=description,
                                  rerendering_round=rerendering_round, url=url)
        else:
            return AdditionalData(in_channel=additional_data_raw, message_id=None, title=None, description=None,
                                  rerendering_round=None, url=None)

    def serialize(self):
        return [self.in_channel, self.message_id, self.title, self.description, self.rerendering_round, self.url]