"""Run ``faustus_mail.py`` with Faustus's Python so the mail password never leaves Faustus.

The Faustus folder comes from the ``mail.faustus_dir`` setting, ``PHILEAS_FAUSTUS_DIR`` / ``FAUSTUS_DIR``, or a
``faustus`` folder next to this app. ``mail.faustus_owner`` picks the Faustus user when several have accounts.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

from ..config import REPO_ROOT

HELPER = Path(__file__).with_name("faustus_mail.py")
TIMEOUT_S = 180
STATUS_TTL_S = 300.0


class FaustusMail:
    def __init__(self, setting: Callable[[str, str], str], secret: Callable[[str], str], *,
                 runner: Optional[Callable[..., Any]] = None, clock: Callable[[], float] = time.time):
        self.setting = setting
        self.secret = secret
        self.runner = runner or subprocess.run
        self.clock = clock
        self._status: Optional[tuple[float, str, dict[str, Any]]] = None

    def faustus_dir(self) -> Optional[Path]:
        raw = [self.setting("mail.faustus_dir", ""), self.secret("FAUSTUS_DIR"), os.environ.get("FAUSTUS_DIR", "")]
        candidates = [Path(r).expanduser() for r in raw if r and r.strip()]
        if not any(r and r.strip() for r in raw):
            candidates += [REPO_ROOT.parent / "faustus", REPO_ROOT.parent.parent / "faustus"]
        for path in candidates:
            try:
                if (path / "mcp_servers" / "email_server.py").is_file():
                    return path.resolve()
            except OSError:
                continue
        return None

    @staticmethod
    def python_of(root: Path) -> Optional[str]:
        for rel in ("venv/Scripts/python.exe", ".venv/Scripts/python.exe", "venv/bin/python", ".venv/bin/python"):
            if (root / rel).is_file():
                return str(root / rel)
        return None

    def call(self, request: dict[str, Any], timeout: float = TIMEOUT_S) -> dict[str, Any]:
        root = self.faustus_dir()
        if root is None:
            return {"ok": False, "error": "Faustus folder not found (set it in Settings → Mail)"}
        python = self.python_of(root)
        if python is None:
            return {"ok": False, "error": "Faustus has no venv with Python"}
        owner = self.setting("mail.faustus_owner", "")
        if owner:
            request = {**request, "owner": owner}
        env = {k: v for k, v in os.environ.items() if not k.startswith("PHILEAS_")}
        env["PYTHONIOENCODING"] = "utf-8"
        try:
            done = self.runner([python, str(HELPER), str(root)], input=json.dumps(request), capture_output=True, text=True,
                               encoding="utf-8", timeout=timeout, cwd=str(root), env=env,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "the mail read took too long"}
        except (OSError, subprocess.SubprocessError) as exc:
            return {"ok": False, "error": f"mail helper: {type(exc).__name__}"}
        lines = [line for line in (getattr(done, "stdout", "") or "").splitlines() if line.strip().startswith("{")]
        try:
            answer = json.loads(lines[-1]) if lines else {}
        except ValueError:
            answer = {}
        if not isinstance(answer, dict) or "ok" not in answer:
            return {"ok": False, "error": f"mail helper exit {getattr(done, 'returncode', '?')}"}
        return answer

    def status(self, refresh: bool = False) -> dict[str, Any]:
        key = str(self.faustus_dir() or "") + "|" + self.setting("mail.faustus_owner", "")
        cached = self._status
        if cached and not refresh and cached[1] == key and self.clock() - cached[0] < (STATUS_TTL_S if cached[2].get("ok") else 30):
            return cached[2]
        answer = self.call({"action": "status"}, timeout=60)
        answer["faustus_dir"] = str(self.faustus_dir() or "")
        self._status = (self.clock(), key, answer)
        return answer

    def scan(self, *, since_days: int, limit: int, skip: list[str], query: str = "", travel: bool = False, deep: bool = False) -> dict[str, Any]:
        """``deep`` only matters to :class:`MailSource`; this reader always searches the whole window."""
        return self.call({"action": "scan", "since_days": since_days, "max": limit, "skip": skip, "query": query, "travel": travel})


# ====================================================================== the family hub's mail gateway (pattern 2)
SOURCE_MODES = ("auto", "hub", "faustus")      # mail.source: the hub's mail gateway, Faustus's own helper, or the hub with a fallback
HUB_PAGE_MAX = 500
HUB_MAX_PAGES = 6                               # pages read in one scan: a long backlog is finished by the next scans
WATERMARK_KEY = "mail.hub.since_id"             # the hub's message id up to which Phileas has read
CARRIER_DOMAINS_EXTRA = ("paack.co", "correosexpress.com", "zeleris.com", "cainiao.com", "dpd.com", "dpd.es", "fedex.com", "tnt.com", "postnl.nl")


def interest_spec(travel: bool) -> dict[str, Any]:
    """What Phileas reads today, as a hub interest: the subject words shipping mail carries (plus booking words when the travel facet is
    on) and the sender domains of the shops and carriers it knows."""
    from .faustus_mail import SUBJECT_TERMS, TRAVEL_TERMS
    from .parse import CARRIER_SENDERS, MERCHANTS
    domains = sorted({*MERCHANTS, *CARRIER_SENDERS, *CARRIER_DOMAINS_EXTRA})
    return {"subject_terms": list(SUBJECT_TERMS) + (list(TRAVEL_TERMS) if travel else []), "from_domains": domains}


class MailSource:
    """Where the engine's mail comes from: the family hub's mail gateway when it is ready (``mail.source`` = ``auto`` | ``hub``), Faustus's own
    helper otherwise (``faustus``, or ``auto`` when the hub is away). The messages reach the SAME parsing code either way.

    * a normal scan reads the hub from a stored watermark (``mail.hub.since_id``), oldest first, and only mail that matches the interest
      registered by :func:`interest_spec`; the watermark moves when the engine has stored the messages (:meth:`commit`);
    * a deep scan (an explicit ``since_days`` or a ``query``) goes to Faustus's helper in ``auto`` (it can look further back than the hub
      stored); in ``hub`` it re-reads the hub's stored mail from the start, filtered by the query, without touching the watermark;
    * after the engine files a message, :meth:`claim` tells the hub "this mail is mine" (a hint, never an error).

    ``hub_mail`` is injectable: an object with ``available/register_interest/messages/claim`` (default: ``hoard_link.fam_mail``)."""

    def __init__(self, own: Any, settings_get: Callable[[str, Optional[str]], Optional[str]], settings_set: Callable[[str, str], None], *,
                 hub_mail: Any = None, clock: Callable[[], float] = time.time):
        self.own = own
        self.get = settings_get
        self.put = settings_set
        self.clock = clock
        self._hub_mail = hub_mail
        self._registered: Optional[str] = None
        self._pending_since: Optional[int] = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ the pieces the engine and the API already use
    def faustus_dir(self) -> Optional[Path]:
        return self.own.faustus_dir()

    def status(self, refresh: bool = False) -> dict[str, Any]:
        answer = dict(self.own.status(refresh=refresh))
        answer["source"] = self.source_status()
        return answer

    # ------------------------------------------------------------------ the hub
    @property
    def hub(self) -> Any:
        if self._hub_mail is None:
            from ..hoard_link import fam_mail
            self._hub_mail = fam_mail
        return self._hub_mail

    def source_setting(self) -> str:
        value = str(self.get("mail.source", "auto") or "auto").strip().lower()
        return value if value in SOURCE_MODES else "auto"

    def hub_up(self) -> bool:
        try:
            return bool(self.hub.available())
        except Exception:  # noqa: BLE001
            return False

    def source_status(self) -> dict[str, Any]:
        setting = self.source_setting()
        up = self.hub_up() if setting != "faustus" else False
        return {"setting": setting, "effective": "hub" if (setting == "hub" or (setting == "auto" and up)) else "faustus", "hub_available": up,
                "interest_registered": self._registered is not None, "hub_since_id": int(self.get(WATERMARK_KEY, "0") or 0)}

    def forget_interest(self) -> None:
        with self._lock:
            self._registered = None

    def ensure_interest(self, travel: bool, *, force: bool = False) -> dict[str, Any]:
        """Tell the hub which mail Phileas wants. Once per process, and again when the travel facet is switched or ``force`` says so."""
        spec = interest_spec(travel)
        signature = f"{'t' if travel else 'p'}:{len(spec['subject_terms'])}:{len(spec['from_domains'])}"
        with self._lock:
            if not force and self._registered == signature:
                return {"ok": True, "cached": True}
        try:
            answer = self.hub.register_interest(spec)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"hub interest: {type(exc).__name__}"}
        if isinstance(answer, dict) and answer.get("ok"):
            with self._lock:
                self._registered = signature
            return {"ok": True}
        return {"ok": False, "error": str((answer or {}).get("error") or "the hub refused the interest")[:200]}

    def _scan_hub(self, days: int, limit: int, skip: list[str], query: str, travel: bool, deep: bool) -> dict[str, Any]:
        registered = self.ensure_interest(travel)
        if not registered.get("ok"):
            return {"ok": False, "error": registered.get("error") or "hub interest failed", "accounts": [], "messages": [], "via": "hub"}
        since = 0 if deep else int(self.get(WATERMARK_KEY, "0") or 0)
        cutoff = self.clock() - int(days) * 86400
        skipped = set(skip)
        words = [w for w in query.lower().split() if w]
        out: list[dict[str, Any]] = []
        read = 0
        last = since
        more = False
        for _ in range(HUB_MAX_PAGES):
            page = self.hub.messages(since_id=last, limit=HUB_PAGE_MAX, full=True)
            if not page.get("ok"):
                if not read:
                    return {"ok": False, "error": str(page.get("error") or "hub mail failed")[:200], "accounts": [], "messages": [], "via": "hub"}
                break
            raw = [m for m in page.get("messages") or [] if isinstance(m, dict)]
            read += len(raw)
            for m in raw:
                ts = m.get("ts")
                mid = str(m.get("message_id") or "")
                if not mid or mid in skipped or (ts and float(ts) < cutoff):
                    continue
                if words:
                    hay = f"{m.get('subject') or ''} {m.get('text') or ''} {m.get('from_address') or ''}".lower()
                    if not all(w in hay for w in words):
                        continue
                out.append({"message_id": mid, "subject": m.get("subject") or "", "from_name": m.get("from_name") or "",
                            "from_address": str(m.get("from_address") or m.get("from_addr") or "").lower(), "ts": ts,
                            "text": m.get("text") or "", "links": m.get("links") or [], "account": "hub", "hub_id": m.get("id")})
            last = int(page.get("last_id") or last)
            more = len(raw) >= HUB_PAGE_MAX
            if not more or len(out) >= limit:
                break
        out.sort(key=lambda m: m.get("ts") or 0, reverse=True)
        self._pending_since = None if deep else last
        return {"ok": True, "error": "", "accounts": [{"account": "hub", "matches": read, "new": len(out)}], "messages": out, "via": "hub",
                "more": more}

    def scan(self, *, since_days: int, limit: int, skip: list[str], query: str = "", travel: bool = False, deep: bool = False) -> dict[str, Any]:
        mode = self.source_setting()
        use_hub = mode == "hub" or (mode == "auto" and self.hub_up() and not (deep and self.own.faustus_dir() is not None))
        if use_hub:
            answer = self._scan_hub(since_days, limit, skip, query, travel, deep)
            if answer.get("ok") or mode == "hub":
                return answer
            # auto: the hub could not give the mail this time, so Faustus's own helper reads it
        return self.own.scan(since_days=since_days, limit=limit, skip=skip, query=query, travel=travel)

    def commit(self) -> None:
        """Remember how far the hub's mail was read. The engine calls it once the messages of a scan are stored."""
        pending, self._pending_since = self._pending_since, None
        if pending is not None:
            self.put(WATERMARK_KEY, str(pending))

    def claim(self, hub_id: Any, kind: str, ref: str) -> None:
        """Tell the hub "this mail is mine" so it leaves the unowned tray. Errors are ignored: claims are hints."""
        if hub_id in (None, ""):
            return
        try:
            self.hub.claim([int(hub_id)], kind, ref)
        except Exception:  # noqa: BLE001
            pass
