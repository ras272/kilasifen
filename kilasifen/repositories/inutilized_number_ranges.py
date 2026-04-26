"""Inutilized number range repository interface."""

from abc import ABC, abstractmethod

from kilasifen.domain.events.inutilized_ranges import InutilizedNumberRange


class InutilizedNumberRangeRepository(ABC):
    """Persistence contract for inutilized number ranges."""

    @abstractmethod
    def save(self, range_item: InutilizedNumberRange) -> InutilizedNumberRange:
        """Persist one inutilized number range."""

    @abstractmethod
    def list_overlapping(
        self,
        *,
        emitter_id: str,
        document_type: str,
        establishment: str,
        point: str,
        number_from: int,
        number_to: int,
        approved_only: bool = False,
    ) -> list[InutilizedNumberRange]:
        """List ranges that overlap a requested interval."""

    @abstractmethod
    def get_max_approved_end_covering_number(
        self,
        *,
        emitter_id: str,
        document_type: str,
        establishment: str,
        point: str,
        number: int,
    ) -> int | None:
        """Return max approved range end that contains the number."""
