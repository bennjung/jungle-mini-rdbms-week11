"""Phase 1 shared exception hierarchy."""


class MiniRDBMSError(Exception):
    """Base exception for all Phase 1 Mini RDBMS errors."""


class SqlSyntaxError(MiniRDBMSError):
    """Raised when SQL lexing or syntax parsing fails."""


class SchemaError(MiniRDBMSError):
    """Raised on missing table/column, column count mismatch, or direct id input."""


class TypeMismatchError(MiniRDBMSError):
    """Raised on type mismatch, invalid DATE format, or invalid NULL comparison."""


class StorageError(MiniRDBMSError):
    """Raised on file I/O errors or corrupted CSV/metadata files."""
