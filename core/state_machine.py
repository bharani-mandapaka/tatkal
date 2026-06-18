from enum import Enum, auto


class BookingState(Enum):
    IDLE = auto()
    LOGGING_IN = auto()
    PREFILLING_FORM = auto()
    WAITING_FOR_WINDOW = auto()
    SEARCHING = auto()
    READING_AVAILABILITY = auto()
    AWAITING_USER_APPROVAL = auto()
    TRYING_NEXT_CLASS = auto()
    SELECTING_TRAIN = auto()
    FILLING_PASSENGERS = auto()
    SOLVING_CAPTCHA = auto()
    SUBMITTING = auto()
    PAYING = auto()
    CONFIRMED = auto()
    REPORTING_FAILURE = auto()
    FAILED = auto()
