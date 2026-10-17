"""Endpoint-bound operating-system credentials, with no plaintext fallback.

The desktop can store or remove an explicitly entered credential. It never returns
stored credential values to the renderer. Gateway processes retrieve only the
credential bound to their exact source identifier and endpoint.
"""
from __future__ import annotations

import argparse
import ctypes
import getpass
import hashlib
import json
import os
import shutil
import subprocess
import sys
from ctypes import wintypes

SERVICE = "io.driftguard.desktop.http"
UNAVAILABLE = "The operating system credential store is unavailable or locked."


class CredentialError(RuntimeError):
    pass


def account(server_id: str, endpoint: str) -> str:
    return hashlib.sha256((server_id + "\0" + endpoint).encode("utf-8")).hexdigest()


def _mac():
    try:
        security = ctypes.CDLL("/System/Library/Frameworks/Security.framework/Security")
        core = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        security.SecKeychainFindGenericPassword.argtypes = [
            ctypes.c_void_p, ctypes.c_uint32, ctypes.c_char_p, ctypes.c_uint32,
            ctypes.c_char_p, ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p)]
        security.SecKeychainFindGenericPassword.restype = ctypes.c_int32
        security.SecKeychainAddGenericPassword.argtypes = [
            ctypes.c_void_p, ctypes.c_uint32, ctypes.c_char_p, ctypes.c_uint32,
            ctypes.c_char_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_void_p]
        security.SecKeychainAddGenericPassword.restype = ctypes.c_int32
        security.SecKeychainItemModifyAttributesAndData.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p]
        security.SecKeychainItemModifyAttributesAndData.restype = ctypes.c_int32
        security.SecKeychainItemDelete.argtypes = [ctypes.c_void_p]
        security.SecKeychainItemDelete.restype = ctypes.c_int32
        security.SecKeychainItemFreeContent.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        core.CFRelease.argtypes = [ctypes.c_void_p]
        return security, core
    except (OSError, AttributeError) as error:
        raise CredentialError(UNAVAILABLE) from error


def _mac_read(identity: str) -> str | None:
    security, _ = _mac()
    service, name = SERVICE.encode(), identity.encode()
    length, data = ctypes.c_uint32(), ctypes.c_void_p()
    status = security.SecKeychainFindGenericPassword(
        None, len(service), service, len(name), name,
        ctypes.byref(length), ctypes.byref(data), None)
    if status == -25300:
        return None
    if status != 0:
        raise CredentialError(UNAVAILABLE)
    try:
        return ctypes.string_at(data, length.value).decode("utf-8")
    finally:
        security.SecKeychainItemFreeContent(None, data)


def _mac_write(identity: str, secret: str | None) -> None:
    security, core = _mac()
    service, name = SERVICE.encode(), identity.encode()
    item = ctypes.c_void_p()
    found = security.SecKeychainFindGenericPassword(
        None, len(service), service, len(name), name, None, None, ctypes.byref(item))
    if found not in {0, -25300}:
        raise CredentialError(UNAVAILABLE)
    try:
        if secret is None:
            status = security.SecKeychainItemDelete(item) if found == 0 else 0
        elif found == 0:
            encoded = secret.encode()
            status = security.SecKeychainItemModifyAttributesAndData(item, None, len(encoded), encoded)
        else:
            encoded = secret.encode()
            status = security.SecKeychainAddGenericPassword(
                None, len(service), service, len(name), name, len(encoded), encoded, None)
        if status != 0:
            raise CredentialError(UNAVAILABLE)
    finally:
        if item.value:
            core.CFRelease(item)


class _Credential(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD), ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR), ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME), ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)), ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD), ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR),
    ]


def _windows():
    try:
        api = ctypes.WinDLL("Advapi32", use_last_error=True)
        api.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                 ctypes.POINTER(ctypes.POINTER(_Credential))]
        api.CredReadW.restype = wintypes.BOOL
        api.CredWriteW.argtypes = [ctypes.POINTER(_Credential), wintypes.DWORD]
        api.CredWriteW.restype = wintypes.BOOL
        api.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
        api.CredDeleteW.restype = wintypes.BOOL
        api.CredFree.argtypes = [ctypes.c_void_p]
        return api
    except (OSError, AttributeError) as error:
        raise CredentialError(UNAVAILABLE) from error


def _windows_read(identity: str) -> str | None:
    api = _windows()
    output = ctypes.POINTER(_Credential)()
    if not api.CredReadW(SERVICE + ":" + identity, 1, 0, ctypes.byref(output)):
        if ctypes.get_last_error() == 1168:
            return None
        raise CredentialError(UNAVAILABLE)
    try:
        value = output.contents
        return ctypes.string_at(value.CredentialBlob, value.CredentialBlobSize).decode("utf-8")
    finally:
        api.CredFree(output)


def _windows_write(identity: str, secret: str | None) -> None:
    api = _windows()
    target = SERVICE + ":" + identity
    if secret is None:
        if not api.CredDeleteW(target, 1, 0) and ctypes.get_last_error() != 1168:
            raise CredentialError(UNAVAILABLE)
        return
    raw = secret.encode()
    blob = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
    value = _Credential(Type=1, TargetName=target, CredentialBlobSize=len(raw),
                        CredentialBlob=blob, Persist=2, UserName=identity)
    if not api.CredWriteW(ctypes.byref(value), 0):
        raise CredentialError(UNAVAILABLE)


def _secret_tool(identity: str, secret: str | None, *, remove: bool = False) -> str | None:
    tool = shutil.which("secret-tool")
    if tool is None:
        raise CredentialError(UNAVAILABLE)
    operation = ["clear"] if remove else (["lookup"] if secret is None else ["store", "--label=MCP DriftGuard"])
    try:
        result = subprocess.run(
            [tool, *operation, "service", SERVICE, "account", identity],
            input=(secret + "\n").encode() if secret is not None else None,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=20, check=False)
        if result.returncode == 1 and secret is None and not remove:
            return None
        if result.returncode != 0:
            raise CredentialError(UNAVAILABLE)
        return result.stdout.decode("utf-8").rstrip("\n") if operation == ["lookup"] else None
    except (OSError, subprocess.TimeoutExpired, UnicodeError) as error:
        raise CredentialError(UNAVAILABLE) from error


def read(server_id: str, endpoint: str) -> str | None:
    identity = account(server_id, endpoint)
    if sys.platform == "darwin":
        return _mac_read(identity)
    if os.name == "nt":
        return _windows_read(identity)
    return _secret_tool(identity, None)


def write(server_id: str, endpoint: str, secret: str | None) -> None:
    if secret is not None and (
        not isinstance(secret, str) or not 8 <= len(secret) <= 2048
        or any(ord(char) < 33 or ord(char) > 126 for char in secret)
    ):
        raise ValueError("A bearer credential must contain 8–2048 printable non-space ASCII characters")
    identity = account(server_id, endpoint)
    if sys.platform == "darwin":
        _mac_write(identity, secret)
    elif os.name == "nt":
        _windows_write(identity, secret)
    else:
        _secret_tool(identity, secret, remove=secret is None)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage an endpoint-bound OS credential without a plaintext fallback")
    parser.add_argument("action", choices=("set", "delete"))
    parser.add_argument("--server-id", required=True)
    parser.add_argument("--url", required=True)
    args = parser.parse_args(argv)
    try:
        from .gateway_http import HttpConfig
        HttpConfig(args.server_id, args.url)
        secret = getpass.getpass("Bearer credential: ") if args.action == "set" else None
        write(args.server_id, args.url, secret)
        print(json.dumps({"ok": True, "stored": args.action == "set"}))
        return 0
    except (ValueError, CredentialError):
        print("Credential operation failed. Check the endpoint and unlock the OS credential store.",
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
