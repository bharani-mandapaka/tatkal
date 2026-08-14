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
    async def login_manual(self) -> bool:
        """
        Navigate to IRCTC and let a human complete login themselves in the
        visible browser window, then verify success. For use when automated
        credential entry is being blocked by anti-bot detection at the auth
        endpoint (confirmed live 2026-08-14: IRCTC's WAF returned HTTP 510
        on the automated login POST while a manual login succeeded moments
        earlier from the same machine).
        """
        ...

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
    async def read_availability_for_class(self, train_number: str, travel_class: str) -> str: ...

    @abstractmethod
    async def fill_passenger_details(self, config: BookingConfig) -> None: ...

    @abstractmethod
    async def get_captcha_image(self) -> bytes: ...

    @abstractmethod
    async def fill_captcha(self, text: str) -> None: ...

    @abstractmethod
    async def submit_passenger_form(self) -> None: ...

    @abstractmethod
    async def handle_aadhaar_otp_if_present(self) -> bool:
        """
        Check whether IRCTC is showing the Aadhaar-linked OTP prompt
        (mandatory for all Tatkal bookings since July 2025). Its exact
        position in the flow is unconfirmed — every live-tested run so far
        has been GENERAL quota, which does not trigger it — so callers may
        check at more than one point. Must return False near-instantly when
        the prompt isn't present so it doesn't add latency to the common case.

        If present: pause and let a human enter the OTP themselves in the
        visible browser window (same hand-off pattern as login_manual()),
        then return True once they confirm it's been submitted.
        """
        ...

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
