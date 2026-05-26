from enum import Enum, auto


class BookingState(Enum):
    IDLE = auto()
    LOGGING_IN = auto()
    PREFILLING_FORM = auto()
    WAITING_FOR_WINDOW = auto()
    SEARCHING = auto()
    SELECTING_TRAIN = auto()
    FILLING_PASSENGERS = auto()
    SOLVING_CAPTCHA = auto()
    SUBMITTING = auto()
    PAYING = auto()
    CONFIRMED = auto()
    FAILED = auto()
