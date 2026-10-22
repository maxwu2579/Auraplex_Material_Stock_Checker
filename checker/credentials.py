"""Windows per-user Credential Manager storage. No environment, CLI or plaintext-file fallback."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os

TARGET = 'Auraplex/MaterialStockChecker/DeepSeek/v1'


class CredentialError(Exception):
    pass


def validate_key(key):
    if type(key) is not str or not 1 <= len(key) <= 512 or not key.isascii() or any(
            ord(c) <= 32 or ord(c) >= 127 for c in key):
        raise CredentialError('Invalid API key format.')
    return key


class _Credential(ctypes.Structure):
    _fields_ = [('Flags', wintypes.DWORD), ('Type', wintypes.DWORD), ('TargetName', wintypes.LPWSTR),
                ('Comment', wintypes.LPWSTR), ('LastWritten', wintypes.FILETIME),
                ('CredentialBlobSize', wintypes.DWORD), ('CredentialBlob', ctypes.POINTER(ctypes.c_ubyte)),
                ('Persist', wintypes.DWORD), ('AttributeCount', wintypes.DWORD),
                ('Attributes', ctypes.c_void_p), ('TargetAlias', wintypes.LPWSTR), ('UserName', wintypes.LPWSTR)]


class WindowsKeyStore:
    """The current interactive user's Windows vault; never an installer/service account's key.

    Other programs running as this user may access the credential. Windows account security is still required.
    """
    def __init__(self, target=TARGET):
        if type(target) is not str or not target or len(target) > 250 or '\x00' in target:
            raise CredentialError('Invalid credential target.')
        self.target = target

    @staticmethod
    def _api():
        if os.name != 'nt':
            raise CredentialError('Windows Credential Manager is required.')
        api = ctypes.WinDLL('Advapi32.dll', use_last_error=True)
        api.CredWriteW.argtypes = [ctypes.POINTER(_Credential), wintypes.DWORD]
        api.CredWriteW.restype = wintypes.BOOL
        api.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  ctypes.POINTER(ctypes.POINTER(_Credential))]
        api.CredReadW.restype = wintypes.BOOL
        api.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
        api.CredDeleteW.restype = wintypes.BOOL
        api.CredFree.argtypes = [ctypes.c_void_p]
        api.CredFree.restype = None
        return api

    def save(self, key):
        raw = validate_key(key).encode('ascii')
        api = self._api()
        blob = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
        credential = _Credential(Type=1, TargetName=self.target, CredentialBlobSize=len(raw),
                                 CredentialBlob=blob, Persist=2, UserName='DeepSeek API')
        try:
            if not api.CredWriteW(ctypes.byref(credential), 0):
                raise CredentialError('Windows credential save failed.')
        finally:
            ctypes.memset(blob, 0, len(raw))

    def load(self):
        api = self._api()
        pointer = ctypes.POINTER(_Credential)()
        if not api.CredReadW(self.target, 1, 0, ctypes.byref(pointer)):
            if ctypes.get_last_error() == 1168:  # ERROR_NOT_FOUND: first use, no key
                return None
            raise CredentialError('Windows credential read failed.')
        try:
            value = pointer.contents
            if not 1 <= value.CredentialBlobSize <= 512:
                raise CredentialError('Invalid stored credential.')
            try:
                return validate_key(ctypes.string_at(value.CredentialBlob, value.CredentialBlobSize).decode('ascii'))
            except UnicodeError:
                raise CredentialError('Invalid stored credential.') from None
        finally:
            if pointer.contents.CredentialBlob:
                ctypes.memset(pointer.contents.CredentialBlob, 0, pointer.contents.CredentialBlobSize)
            api.CredFree(pointer)

    def delete(self):
        api = self._api()
        if not api.CredDeleteW(self.target, 1, 0) and ctypes.get_last_error() != 1168:
            raise CredentialError('Windows credential removal failed.')
