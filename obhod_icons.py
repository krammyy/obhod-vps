"""Application icons for the OBHOD lists.

Windows: the exe icon is pulled through Shell32/ExtractIconEx + GDI, without extra
dependencies. Other platforms get None and the GUI draws a letter placeholder.
"""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from pathlib import Path

_IS_WIN = sys.platform == "win32"

HICON = ctypes.c_void_p
HGDIOBJ = ctypes.c_void_p
HDC = ctypes.c_void_p


class ICONINFO(ctypes.Structure):
    _fields_ = [
        ("fIcon", ctypes.c_bool),
        ("xHotspot", ctypes.c_uint),
        ("yHotspot", ctypes.c_uint),
        ("hbmMask", ctypes.c_void_p),
        ("hbmColor", ctypes.c_void_p),
    ]


class BITMAP(ctypes.Structure):
    _fields_ = [
        ("bmType", ctypes.c_long),
        ("bmWidth", ctypes.c_long),
        ("bmHeight", ctypes.c_long),
        ("bmWidthBytes", ctypes.c_long),
        ("bmPlanes", ctypes.c_ushort),
        ("bmBitsPixel", ctypes.c_ushort),
        ("bmBits", ctypes.c_void_p),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", ctypes.c_uint32),
        ("biWidth", ctypes.c_int32),
        ("biHeight", ctypes.c_int32),
        ("biPlanes", ctypes.c_uint16),
        ("biBitCount", ctypes.c_uint16),
        ("biCompression", ctypes.c_uint32),
        ("biSizeImage", ctypes.c_uint32),
        ("biXPelsPerMeter", ctypes.c_int32),
        ("biYPelsPerMeter", ctypes.c_int32),
        ("biClrUsed", ctypes.c_uint32),
        ("biClrImportant", ctypes.c_uint32),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", ctypes.c_uint32 * 3)]


def _api():
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)

    shell32.ExtractIconExW.argtypes = [wintypes.LPCWSTR, ctypes.c_int,
                                       ctypes.POINTER(HICON), ctypes.POINTER(HICON), ctypes.c_uint]
    shell32.ExtractIconExW.restype = ctypes.c_uint
    user32.GetIconInfo.argtypes = [HICON, ctypes.POINTER(ICONINFO)]
    user32.GetIconInfo.restype = ctypes.c_bool
    user32.DestroyIcon.argtypes = [HICON]
    user32.DestroyIcon.restype = ctypes.c_bool
    gdi32.GetObjectW.argtypes = [HGDIOBJ, ctypes.c_int, ctypes.c_void_p]
    gdi32.GetObjectW.restype = ctypes.c_int
    gdi32.CreateCompatibleDC.argtypes = [HDC]
    gdi32.CreateCompatibleDC.restype = HDC
    gdi32.SelectObject.argtypes = [HDC, HGDIOBJ]
    gdi32.SelectObject.restype = HGDIOBJ
    gdi32.GetDIBits.argtypes = [HDC, HGDIOBJ, ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p,
                                ctypes.POINTER(BITMAPINFO), ctypes.c_uint]
    gdi32.GetDIBits.restype = ctypes.c_int
    gdi32.DeleteDC.argtypes = [HDC]
    gdi32.DeleteDC.restype = ctypes.c_bool
    return user32, gdi32, shell32


def _extract_windows(path: Path, size: int):
    from PIL import Image

    user32, gdi32, shell32 = _api()
    large = HICON()
    small = HICON()
    count = shell32.ExtractIconExW(str(path), 0, ctypes.byref(large), ctypes.byref(small), 1)
    hicon = large.value or small.value
    if count <= 0 or not hicon:
        return None
    try:
        info = ICONINFO()
        if not user32.GetIconInfo(hicon, ctypes.byref(info)) or not info.hbmColor:
            return None
        bitmap = BITMAP()
        if not gdi32.GetObjectW(info.hbmColor, ctypes.sizeof(bitmap), ctypes.byref(bitmap)):
            return None
        width, height = int(bitmap.bmWidth), int(bitmap.bmHeight)
        if not width or not height:
            return None
        dc = gdi32.CreateCompatibleDC(None)
        old = gdi32.SelectObject(dc, info.hbmColor)
        try:
            header = BITMAPINFOHEADER()
            header.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            header.biWidth = width
            header.biHeight = -height
            header.biPlanes = 1
            header.biBitCount = 32
            header.biCompression = 0
            info_struct = BITMAPINFO()
            info_struct.bmiHeader = header
            buffer = ctypes.create_string_buffer(width * height * 4)
            got = gdi32.GetDIBits(dc, info.hbmColor, 0, height, buffer, ctypes.byref(info_struct), 0)
        finally:
            gdi32.SelectObject(dc, old)
            gdi32.DeleteDC(dc)
        if not got:
            return None
        image = Image.frombuffer("RGBA", (width, height), buffer, "raw", "BGRA", 0, 1)
        return image.resize((size, size), Image.LANCZOS)
    finally:
        user32.DestroyIcon(hicon)


def load_icon(path: str | Path, size: int = 20):
    """Icon of an executable as a PIL image, or None when unavailable."""
    if not _IS_WIN:
        return None
    target = Path(str(path))
    if not target.is_file():
        return None
    try:
        return _extract_windows(target, size)
    except Exception:
        return None
