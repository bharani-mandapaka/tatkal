from abc import ABC, abstractmethod


class CaptchaPort(ABC):
    @abstractmethod
    async def solve(self, image_bytes: bytes) -> str: ...
