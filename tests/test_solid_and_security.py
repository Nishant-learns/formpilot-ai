"""Comprehensive verification of SOLID architecture contracts and sensitive operation guards."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.core.biometrics import BiometricCompressor
from backend.core.dom_scanner import DOMScanner
from backend.core.interfaces import (
    CanClassifyField,
    CanProcessBiometrics,
    CanProtectSensitiveData,
    CanScanDOM,
)
from backend.core.security_hardening import SensitiveOperationGuard
from backend.core.vault_crypto import VaultCipher, load_or_create_key
from backend.main import app


def test_solid_architecture_protocols_adherence():
    """Verify that core engines adhere to their respective SOLID role-focused Protocols."""
    # S - Single Responsibility & I - Interface Segregation
    assert isinstance(DOMScanner, CanClassifyField)
    assert issubclass(DOMScanner, CanClassifyField)
    assert isinstance(DOMScanner(), CanScanDOM)
    assert isinstance(BiometricCompressor(), CanProcessBiometrics)
    assert issubclass(BiometricCompressor, CanProcessBiometrics)
    cipher = VaultCipher(load_or_create_key())
    assert isinstance(cipher, CanProtectSensitiveData)


def test_sensitive_operation_guard_blocks_unauthorized_execution():
    """Verify that sensitive actions cannot execute autonomously without a human gate."""
    with pytest.raises(PermissionError, match="SENSITIVE OPERATION BLOCKED"):
        SensitiveOperationGuard.assert_human_authorization_required(
            "PAYMENT_EXECUTION", has_human_gate=False
        )

    with pytest.raises(PermissionError, match="SENSITIVE OPERATION BLOCKED"):
        SensitiveOperationGuard.assert_human_authorization_required(
            "FINAL_APPLICATION_SUBMIT", has_human_gate=False
        )

    # Allowed when human gate is active
    SensitiveOperationGuard.assert_human_authorization_required(
        "PAYMENT_EXECUTION", has_human_gate=True
    )
    SensitiveOperationGuard.assert_human_authorization_required(
        "FINAL_APPLICATION_SUBMIT", has_human_gate=True
    )


def test_constant_time_comparison_safeguard():
    """Verify constant-time verification behavior on secret tokens."""
    token_a = "secret_session_token_xyz_12345"
    token_b = "secret_session_token_xyz_12345"
    token_c = "different_token_abc_67890"

    assert SensitiveOperationGuard.constant_time_compare(token_a, token_b) is True
    assert SensitiveOperationGuard.constant_time_compare(token_a, token_c) is False
    assert SensitiveOperationGuard.constant_time_compare(None, token_a) is False
    assert SensitiveOperationGuard.constant_time_compare(token_a, None) is False


def test_secure_memory_zeroing():
    """Verify sensitive byte arrays are securely zeroed in place."""
    sensitive_buffer = bytearray(b"super_secret_temporary_password")
    assert any(b != 0 for b in sensitive_buffer)

    SensitiveOperationGuard.secure_zero_buffer(sensitive_buffer)
    assert all(b == 0 for b in sensitive_buffer)


def test_security_headers_enforced_on_api_responses():
    """Verify enterprise defense-in-depth headers on public API routes."""
    client = TestClient(app)
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "SAMEORIGIN"
    assert response.headers["X-XSS-Protection"] == "1; mode=block"
    assert "Strict-Transport-Security" in response.headers
    assert "Content-Security-Policy" in response.headers
