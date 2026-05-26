from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from core.models import BookingConfig


@dataclass
class TrainInfo:
    train_number: str
    train_name: str
    availability: str
    fare: Optional[int] = None


class BrowserPort(ABC):
    @abstractmethod
    async def launch(self) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...

    @abstractmethod
    async def login(self, username: str, password: str) -> bool: ...

    @abstractmethod
    async def is_logged_in(self) -> bool: ...

    @abstractmethod
    async def navigate_to_booking(self) -> None: ...

    @abstractmethod
    async def prefill_search_form(self, config: BookingConfig) -> None: ...

    @abstractmethod
    async def search_trains(self) -> None: ...

    @abstractmethod
    async def find_and_select_train(self, train_number: str, travel_class: str) -> TrainInfo: ...

    @abstractmethod
    async def fill_passenger_details(self, config: BookingConfig) -> None: ...

    @abstractmethod
    async def get_captcha_image(self) -> bytes: ...

    @abstractmethod
    async def fill_captcha(self, text: str) -> None: ...

    @abstractmethod
    async def submit_passenger_form(self) -> None: ...

    @abstractmethod
    async def get_booking_confirmation(self) -> dict: ...

    @abstractmethod
    async def screenshot(self, path: str) -> None: ...

    @abstractmethod
    async def ping(self) -> None:
        """
        Lightweight server-side session keep-alive.
        Must make an HTTP request that resets IRCTC's idle-timeout clock
        without disrupting any visible page state.
        Called every 15 s during the pre-window wait.
        """
        ...
