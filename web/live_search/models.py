from dataclasses import dataclass, field


@dataclass
class LiveSearchResult:
    title: str
    author: str = ""
    publisher: str = ""
    library_code: str = ""
    library_name: str = ""
    library_short: str = ""
    platform: str = ""
    provider: str = ""
    image_url: str = ""
    isbn: str = ""
    detail_url: str = ""
    service_type: str = ""
    identifiers: dict = field(default_factory=dict)

    def as_dict(self):
        return {
            "title": self.title,
            "author": self.author,
            "publisher": self.publisher,
            "library_code": self.library_code,
            "library_name": self.library_name,
            "library_short": self.library_short,
            "platform": self.platform,
            "provider": self.provider,
            "image_url": self.image_url,
            "isbn": self.isbn,
            "detail_url": self.detail_url,
            "service_type": self.service_type,
            "identifiers": dict(self.identifiers or {}),
        }
