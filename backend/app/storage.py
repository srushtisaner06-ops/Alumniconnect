"""Private document storage.

Callers depend on `StorageBackend`, never on the filesystem, so moving to S3 / Azure Blob later means adding one
class and changing `STORAGE_BACKEND`. Files are:

  * validated before they are stored (extension allow-list + real content signature + size);
  * stored under a random key the client never chooses (no path traversal, no overwrite, no guessable names);
  * kept outside any web-served directory, and only ever returned by an authorised endpoint (Phase 1).

`validate_upload` does not trust the filename or the Content-Type header: the file's first bytes must match its
extension. This stops `shell.php` renamed to `scan.pdf`, but it is not a malware scan. `SCAN_HOOK` is the place to
plug one in before files are accepted for real use.
"""
import hashlib
import os
import re
import secrets
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from . import config


class StorageError(Exception):
    """A file was rejected, or a key is invalid. The message is safe to show to the person who uploaded it."""


# extension -> (canonical content type, signature the first bytes must start with)
ALLOWED = {
    ".pdf": ("application/pdf", (b"%PDF-",)),
    ".png": ("image/png", (b"\x89PNG\r\n\x1a\n",)),
    ".jpg": ("image/jpeg", (b"\xff\xd8\xff",)),
    ".jpeg": ("image/jpeg", (b"\xff\xd8\xff",)),
}
_KEY_RE = re.compile(r"^[a-f0-9]{32}\.(pdf|png|jpg)$")
SCAN_HOOK = None        # optional callable(data: bytes) that raises StorageError to refuse a file (e.g. an antivirus call)


@dataclass(frozen=True)
class StoredFile:
    key: str
    original_name: str
    content_type: str
    size: int
    sha256: str


def safe_filename(name):
    """Display name only (never used as a path): basename, no control characters, bounded length."""
    base = re.split(r"[\\/]", name or "")[-1]
    base = re.sub(r"[\x00-\x1f\x7f]", "", base).strip().strip(".")
    return (base or "document")[:100]


def validate_upload(filename, data, declared_type=None, max_bytes=None):
    """Return (extension, canonical content type) or raise StorageError."""
    limit = max_bytes or config.MAX_DOCUMENT_BYTES
    if not data:
        raise StorageError("The file is empty")
    if len(data) > limit:
        raise StorageError(f"The file is too large (maximum {limit // (1024 * 1024) or 1} MB)")
    ext = os.path.splitext(safe_filename(filename))[1].lower()
    if ext not in ALLOWED:
        raise StorageError("Only PDF, PNG and JPG files are accepted")
    ctype, sigs = ALLOWED[ext]
    if not any(data.startswith(s) for s in sigs):
        raise StorageError("The file content does not match its type")
    if declared_type and declared_type.split(";")[0].strip().lower() not in (ctype, "application/octet-stream"):
        raise StorageError("The file content does not match its type")
    if SCAN_HOOK:
        SCAN_HOOK(data)
    return ext, ctype


class StorageBackend(ABC):
    @abstractmethod
    def put(self, key, data): ...

    @abstractmethod
    def get(self, key): ...

    @abstractmethod
    def delete(self, key): ...

    @abstractmethod
    def exists(self, key): ...

    def save_upload(self, filename, data, declared_type=None, max_bytes=None):
        """Validate, then store under a fresh random key."""
        ext, ctype = validate_upload(filename, data, declared_type, max_bytes)
        key = secrets.token_hex(16) + (".jpg" if ext == ".jpeg" else ext)
        self.put(key, data)
        return StoredFile(key=key, original_name=safe_filename(filename), content_type=ctype, size=len(data),
                          sha256=hashlib.sha256(data).hexdigest())


class LocalPrivateStorage(StorageBackend):
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.root, 0o700)
        except OSError:                      # e.g. Windows: permissions come from the parent folder
            pass

    def _path(self, key):
        if not isinstance(key, str) or not _KEY_RE.match(key):
            raise StorageError("Invalid file key")
        p = (self.root / key).resolve()
        if p.parent != self.root:            # belt and braces on top of the key pattern
            raise StorageError("Invalid file key")
        return p

    def put(self, key, data):
        p = self._path(key)
        if p.exists():
            raise StorageError("File already exists")        # keys are random; never overwrite
        tmp = p.with_suffix(p.suffix + ".part")
        tmp.write_bytes(data)
        os.replace(tmp, p)                                    # atomic: readers never see a half-written file

    def get(self, key):
        p = self._path(key)
        if not p.is_file():
            raise StorageError("File not found")
        return p.read_bytes()

    def delete(self, key):
        p = self._path(key)
        if p.is_file():
            p.unlink()

    def exists(self, key):
        return self._path(key).is_file()


_storage = None


def get_storage():
    global _storage
    if _storage is None:
        if config.STORAGE_BACKEND != "local":
            raise RuntimeError(f"Unknown STORAGE_BACKEND {config.STORAGE_BACKEND!r} (only 'local' is implemented)")
        _storage = LocalPrivateStorage(config.STORAGE_ROOT)
    return _storage


def reset_storage():
    """For tests: forget the cached backend so a changed STORAGE_ROOT takes effect."""
    global _storage
    _storage = None
