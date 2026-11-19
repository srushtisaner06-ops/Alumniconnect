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


CHUNK = 1024 * 1024          # files are copied, hashed and served one megabyte at a time


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


def size_label(n):
    """Human size for messages: '1 GB', '50 MB', '300 KB'."""
    if n >= 1024 ** 3:
        v = n / 1024 ** 3
        return f"{v:g} GB" if v == int(v) else f"{v:.1f} GB"
    if n >= 1024 ** 2:
        return f"{n // 1024 ** 2} MB"
    return f"{max(1, n // 1024)} KB"


def too_large(limit):
    return StorageError(f"The file is too large (maximum {size_label(limit)})")


def validate_header(filename, head, declared_type=None):
    """The checks that need only the file's name, declared type and first bytes. Return (extension, content type)."""
    ext = os.path.splitext(safe_filename(filename))[1].lower()
    if ext not in ALLOWED:
        raise StorageError("Only PDF, PNG and JPG files are accepted")
    ctype, sigs = ALLOWED[ext]
    if not any(head.startswith(s) for s in sigs):
        raise StorageError("The file content does not match its type")
    if declared_type and declared_type.split(";")[0].strip().lower() not in (ctype, "application/octet-stream"):
        raise StorageError("The file content does not match its type")
    return ext, ctype


def validate_upload(filename, data, declared_type=None, max_bytes=None):
    """Return (extension, canonical content type) or raise StorageError. For a file already in memory."""
    limit = max_bytes or config.MAX_DOCUMENT_BYTES
    if not data:
        raise StorageError("The file is empty")
    if len(data) > limit:
        raise too_large(limit)
    ext, ctype = validate_header(filename, data, declared_type)
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

    @abstractmethod
    def list_keys(self):
        """[(key, modified_epoch_seconds)] for every stored file. Used to sweep orphans."""

    def save_upload(self, filename, data, declared_type=None, max_bytes=None):
        """Validate, then store under a fresh random key."""
        ext, ctype = validate_upload(filename, data, declared_type, max_bytes)
        key = secrets.token_hex(16) + (".jpg" if ext == ".jpeg" else ext)
        self.put(key, data)
        return StoredFile(key=key, original_name=safe_filename(filename), content_type=ctype, size=len(data),
                          sha256=hashlib.sha256(data).hexdigest())

    def put_stream(self, key, head, stream, limit):
        """Store `head` + the rest of `stream` under `key`. -> (size, sha256). A backend should override this to avoid
        holding the whole file in memory; this default does hold it (fine for small files, used only by simple backends)."""
        parts, size, h = [head], len(head), hashlib.sha256(head)
        while True:
            chunk = stream.read(CHUNK)
            if not chunk:
                break
            size += len(chunk)
            if size > limit:
                raise too_large(limit)
            h.update(chunk)
            parts.append(chunk)
        self.put(key, b"".join(parts))
        return size, h.hexdigest()

    def save_stream(self, filename, stream, declared_type=None, max_bytes=None):
        """Like save_upload, for a file-like object: the file is checked from its first bytes, then copied in chunks,
        hashed and size-limited as it goes, so a very large file never has to fit in memory. Nothing is kept if it fails."""
        limit = max_bytes or config.MAX_DOCUMENT_BYTES
        head = stream.read(CHUNK)
        if not head:
            raise StorageError("The file is empty")
        ext, ctype = validate_header(filename, head, declared_type)
        key = secrets.token_hex(16) + (".jpg" if ext == ".jpeg" else ext)
        size, digest = self.put_stream(key, head, stream, limit)
        if SCAN_HOOK:                                    # the hook takes bytes, so a scanner makes this path read the file back
            try:
                SCAN_HOOK(self.get(key))
            except BaseException:
                self.delete(key)
                raise
        return StoredFile(key=key, original_name=safe_filename(filename), content_type=ctype, size=size, sha256=digest)

    def iter_chunks(self, key):
        """The stored file as a sequence of byte chunks (for downloads). Override to read lazily."""
        yield self.get(key)


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

    def put_stream(self, key, head, stream, limit):
        p = self._path(key)
        if p.exists():
            raise StorageError("File already exists")        # keys are random; never overwrite
        tmp = p.with_suffix(p.suffix + ".part")
        h, size = hashlib.sha256(), 0
        try:
            with open(tmp, "wb") as f:
                chunk = head
                while chunk:
                    size += len(chunk)
                    if size > limit:
                        raise too_large(limit)
                    h.update(chunk)
                    f.write(chunk)
                    chunk = stream.read(CHUNK)
            os.replace(tmp, p)                                # atomic: readers never see a half-written file
        except BaseException:
            tmp.unlink(missing_ok=True)                       # a refused or interrupted upload leaves nothing behind
            raise
        return size, h.hexdigest()

    def iter_chunks(self, key):
        p = self._path(key)
        if not p.is_file():
            raise StorageError("File not found")
        with open(p, "rb") as f:
            while True:
                chunk = f.read(CHUNK)
                if not chunk:
                    return
                yield chunk

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

    def list_keys(self):
        return [(p.name, p.stat().st_mtime) for p in self.root.iterdir() if p.is_file() and _KEY_RE.match(p.name)]


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
