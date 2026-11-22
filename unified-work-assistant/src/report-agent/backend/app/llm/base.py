from abc import ABC, abstractmethod

from ..schemas import ParsedWorkReport


class LLMProvider(ABC):
    @abstractmethod
    async def parse_report(
        self, raw_message: str, employee_name: str, project_name: str
    ) -> ParsedWorkReport:
        raise NotImplementedError

