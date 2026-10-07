"""API errors for the upload flow.

These subclass HTTPException, so the existing Phase 1 handler in main.py
renders them as {"error": {"code": ..., "message": ...}}. Messages are
client-safe: they never contain filesystem paths.
"""
from fastapi import HTTPException


class ApiError(HTTPException):
    status_code_default = 400

    def __init__(self, message: str):
        super().__init__(status_code=self.status_code_default, detail=message)


class InvalidUploadError(ApiError):
    status_code_default = 400


class EmptyFileError(ApiError):
    status_code_default = 400


class FileTooLargeError(ApiError):
    status_code_default = 413


class UnsupportedFileTypeError(ApiError):
    status_code_default = 415


class StorageError(ApiError):
    status_code_default = 500
