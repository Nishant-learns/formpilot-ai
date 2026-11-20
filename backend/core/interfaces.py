"""SOLID Principle Interface Contracts & Protocol Definitions for FormPilot.

Implements architectural abstractions ensuring:
- Single Responsibility Principle (SRP): Cohesive, single-purpose service boundaries.
- Open/Closed Principle (OCP): Pluggable strategies extensible without mutating core.
- Liskov Substitution Principle (LSP): Strict substitutability across drivers and adapters.
- Interface Segregation Principle (ISP): Granular, role-focused Protocols.
- Dependency Inversion Principle (DIP): Inversion of control via abstract Protocol bindings.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Protocol, Tuple, runtime_checkable
from playwright.async_api import Page


# =====================================================================
# 1. Interface Segregation: Granular Role-Focused Protocols
# =====================================================================

@runtime_checkable
class CanScanDOM(Protocol):
    """SRP: Solely responsible for inspecting and extracting DOM accessibility trees."""

    async def scan(self, page: Page) -> Dict[str, Any]:
        """Produce a normalized DOM perception snapshot."""
        ...


@runtime_checkable
class CanClassifyField(Protocol):
    """SRP: Solely responsible for mapping machine inputs to semantic schema keys."""

    def classify_field(self, item: Dict[str, Any]) -> Tuple[str, bool]:
        """Return (semantic_key, is_verification_field)."""
        ...


@runtime_checkable
class CanProtectSensitiveData(Protocol):
    """SRP: Solely responsible for cryptographic protection and envelope encryption."""

    def encrypt_bytes(self, plaintext: bytes) -> Dict[str, Any]:
        """Encrypt sensitive plaintext using authenticated ciphers."""
        ...

    def decrypt_bytes(self, envelope: Dict[str, Any]) -> bytes:
        """Decrypt sensitive ciphertext using verified keys."""
        ...


@runtime_checkable
class CanProcessBiometrics(Protocol):
    """SRP: Solely responsible for strict biometric asset formatting and compression."""

    def compress_photograph(
        self,
        image_bytes: bytes,
        target_width: int,
        target_height: int,
        min_kb: float,
        max_kb: float,
    ) -> Dict[str, Any]:
        """Compress applicant photo to strict official specifications."""
        ...

    def compress_signature(
        self,
        image_bytes: bytes,
        target_width: int,
        target_height: int,
        min_kb: float,
        max_kb: float,
    ) -> bytes:
        """Compress candidate signature to official pixel and byte ranges."""
        ...


@runtime_checkable
class CanPromptLLM(Protocol):
    """SRP: Solely responsible for multimodal GenAI interactions and schema mapping."""

    async def prompt(
        self,
        prompt_text: str,
        system_instruction: Optional[str] = None,
        image_bytes: Optional[bytes] = None,
    ) -> str:
        """Query LLM with multimodal inputs and return structured completion."""
        ...


# =====================================================================
# 2. Open/Closed Principle: Extensible Strategy Interfaces
# =====================================================================

class BasePortalStrategy(ABC):
    """OCP: Base strategy for official government portal adapters.

    New exam authorities (UPSC, SSC, NTA, HPSC) are added by extending
    this strategy without modifying the orchestrator core.
    """

    @property
    @abstractmethod
    def authority_name(self) -> str:
        """Unique identifier of the examination or recruitment body."""
        ...

    @abstractmethod
    def identify_current_step(self, page: Page, dom: Dict[str, Any]) -> int:
        """Derive active wizard step number from page state."""
        ...

    @abstractmethod
    def is_terminal_safety_boundary(self, dom: Dict[str, Any]) -> bool:
        """Return True if current view requires mandatory human handoff (payment/final submit)."""
        ...

    @abstractmethod
    def resolve_advance_locator(self, dom: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Identify the safe 'Save & Next' control without clicking final submission."""
        ...


class BaseStorageProvider(ABC):
    """DIP: Abstract persistence provider for run logs, journals, and receipts."""

    @abstractmethod
    def save_record(self, key: str, payload: Dict[str, Any]) -> None:
        """Persist a JSON record."""
        ...

    @abstractmethod
    def load_record(self, key: str) -> Optional[Dict[str, Any]]:
        """Retrieve a persisted record by key."""
        ...


# =====================================================================
# 3. Liskov Substitution Principle: Swappable Core Engine Contracts
# =====================================================================

class BaseOrchestrator(ABC):
    """LSP: Swappable orchestrator contract for local, cloud, and headless test runners."""

    @abstractmethod
    async def start(self, target_url: str, mode: str = "fill") -> None:
        """Initiate autonomous or guided form operations."""
        ...

    @abstractmethod
    async def pause(self) -> None:
        """Safely halt execution at current section checkpoint."""
        ...

    @abstractmethod
    async def resume(self) -> None:
        """Resume execution following human verification."""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Gracefully release browser pipes, scrub buffers, and finalize audit ledger."""
        ...
