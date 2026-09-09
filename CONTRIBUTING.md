# Contributing

Develop on Windows with Python 3.10 or newer. Run from the repository root:

```powershell
$env:PYTHONPATH = 'src'
python -X utf8 -m unittest discover -s tests
```

Use synthetic fixtures only. Do not submit private CAD models, customer data,
machine paths, credentials, conversion logs, or validation artifacts. Do not
submit proprietary vendor binaries, DLLs, documentation, license material, or
files copied from a separately licensed CAD installation.

Keep local configuration and generated files out of commits. Add focused
automated coverage for behavior changes and run the full suite before opening
a pull request.

diff --git a/SECURITY.md b/SECURITY.md
new file mode 100644
