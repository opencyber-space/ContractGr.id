from __future__ import annotations


class WatcherError(Exception):
    pass


class DuplicityError(WatcherError):
    def __init__(self, aid: str, sn: int, first_said: str, conflict_said: str) -> None:
        self.aid = aid
        self.sn = sn
        self.first_said = first_said
        self.conflict_said = conflict_said
        super().__init__(
            f"Duplicity detected for {aid} at sn={sn}: "
            f"first={first_said} conflict={conflict_said}"
        )


class ValidationError(WatcherError):
    def __init__(self, aid: str, sn: int, reason: str) -> None:
        self.aid = aid
        self.sn = sn
        self.reason = reason
        super().__init__(f"Validation failed for {aid} sn={sn}: {reason}")


class EscrowError(WatcherError):
    pass


class NotWatchedError(WatcherError):
    def __init__(self, aid: str) -> None:
        self.aid = aid
        super().__init__(f"AID {aid} is not being watched")


class AlreadyWatchedError(WatcherError):
    def __init__(self, aid: str) -> None:
        self.aid = aid
        super().__init__(f"AID {aid} is already being watched")


class DBError(WatcherError):
    pass


class PollError(WatcherError):
    def __init__(self, witness: str, reason: str) -> None:
        self.witness = witness
        self.reason = reason
        super().__init__(f"Poll failed for witness {witness}: {reason}")


class RateLimitError(WatcherError):
    pass


class ConfigError(WatcherError):
    pass