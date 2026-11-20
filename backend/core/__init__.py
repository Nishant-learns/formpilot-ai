"""FormPilot Core Engine Package.

Provides autonomous form operations, DOM perception, cryptographic storage,
and safety gates adhering to SOLID principles.
"""

from __future__ import annotations

from .interfaces import (
    CanClassifyField,
    CanProcessBiometrics,
    CanProtectSensitiveData,
    CanPromptLLM,
    CanScanDOM,
    BasePortalStrategy,
    BaseStorageProvider,
    BaseOrchestrator,
)
from .security_hardening import SensitiveOperationGuard, SSRFGuard, AuditHashChain, PIISanitizer

__all__ = [
    "CanClassifyField",
    "CanProcessBiometrics",
    "CanProtectSensitiveData",
    "CanPromptLLM",
    "CanScanDOM",
    "BasePortalStrategy",
    "BaseStorageProvider",
    "BaseOrchestrator",
    "SensitiveOperationGuard",
    "SSRFGuard",
    "AuditHashChain",
    "PIISanitizer",
]
