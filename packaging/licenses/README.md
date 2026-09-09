# Third-party notices

This portable build redistributes the Python runtime and Tcl/Tk, and it is produced with PyInstaller 6.21.0 plus pyinstaller-hooks-contrib 2026.6.

- `PyInstaller-COPYING.txt`: PyInstaller GPL-2.0-or-later terms, Bootloader Exception, Apache-2.0 runtime-hook terms, and related notices.
- `Python-LICENSE.txt`: Python 3.12 PSF License and incorporated software notices from the build runtime.
- `TclTk-LICENSE.txt`: Tcl/Tk BSD-style licensing terms retained for the bundled Tcl/Tk runtime.

PyInstaller's Bootloader Exception permits distributing the combined executable without imposing GPL restrictions merely because the bootloader is embedded. Dependencies retain their own license terms. pyinstaller-hooks-contrib standard hooks are GPL-2.0-or-later build inputs; its runtime hooks are Apache-2.0. See the pinned upstream source for the complete hooks license corresponding to version 2026.6.
