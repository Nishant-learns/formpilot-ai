"""Per-account workspaces.

A FormPilot account is only real if its data is real.  This module owns the
mapping from an account to the objects that touch that account's data:

* a ``VaultManager`` at ``<workspace>/candidate_vault.json``
* a ``DocumentStore`` rooted at ``<workspace>/documents``
* a ``RunStore`` rooted at ``<workspace>/runs``
* one ``FormPilotOrchestrator`` and one ``FormPilotChatAssistant`` so a live
  browser run cannot bleed into another account's cockpit

The legacy single-user demo keeps its own ``Workspace`` object built from the
global stores; the registry only creates one when a request is authenticated.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Optional

from .accounts import Account
from .chat_assistant import FormPilotChatAssistant
from .document_store import DocumentStore
from .facts import FactBook
from .lessons import LessonStore
from .orchestrator import FormPilotOrchestrator
from .portal_accounts import PortalAccountStore
from .run_store import RunStore
from .vault import VaultManager


@dataclass
class Workspace:
    account_id: Optional[str]
    root: Path
    vault_mgr: VaultManager
    document_store: DocumentStore
    run_store: RunStore
    orchestrator: FormPilotOrchestrator
    chat_assistant: FormPilotChatAssistant
    uploads_dir: Path

    @property
    def is_guest(self) -> bool:
        return self.account_id is None


class WorkspaceRegistry:
    """Lazily create and cache one workspace per account id."""

    def __init__(self, broadcast_factory: Callable[[Optional[str]], Callable]):
        self._broadcast_factory = broadcast_factory
        self._workspaces: Dict[str, Workspace] = {}
        self._lock = threading.RLock()

    def get(self, account: Account) -> Workspace:
        with self._lock:
            existing = self._workspaces.get(account.id)
            if existing is not None:
                return existing
            workspace = self._build(account)
            self._workspaces[account.id] = workspace
            return workspace

    def peek(self, account_id: str) -> Optional[Workspace]:
        with self._lock:
            return self._workspaces.get(str(account_id or ""))

    def drop(self, account_id: str) -> None:
        with self._lock:
            self._workspaces.pop(str(account_id or ""), None)

    def _build(self, account: Account) -> Workspace:
        from . import settings

        root = settings.ACCOUNTS_DIR / account.id
        uploads = root / "uploads"
        for directory in (root, uploads, root / "documents", root / "runs"):
            directory.mkdir(parents=True, exist_ok=True)

        vault_mgr = VaultManager(str(root / "candidate_vault.json"), blank=True)
        document_store = DocumentStore(root / "documents")
        run_store = RunStore(root / "runs")
        fact_book = FactBook(str(root / "facts.json"), vault_manager=vault_mgr)
        portal_account_store = PortalAccountStore(str(root / "portal_accounts.json"))
        lesson_store = LessonStore(str(root / "lessons.json"))
        orchestrator = FormPilotOrchestrator(
            broadcast_fn=self._broadcast_factory(account.id),
            vault_mgr=vault_mgr,
            run_store=run_store,
            document_store=document_store,
            uploads_dir=uploads,
            fact_book=fact_book,
            portal_account_store=portal_account_store,
            lesson_store=lesson_store,
        )
        chat_assistant = FormPilotChatAssistant(
            orchestrator=orchestrator,
            vault_mgr=vault_mgr,
        )
        return Workspace(
            account_id=account.id,
            root=root,
            vault_mgr=vault_mgr,
            document_store=document_store,
            run_store=run_store,
            orchestrator=orchestrator,
            chat_assistant=chat_assistant,
            uploads_dir=uploads,
        )
