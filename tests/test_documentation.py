from pathlib import Path
import unittest


class DocumentationContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parents[1]

    def test_public_identity_and_license(self) -> None:
        readme = (self.root / "README.md").read_text(encoding="utf-8")
        license_text = (self.root / "LICENSE").read_text(encoding="utf-8")
        self.assertTrue(readme.startswith("# STEP to ACIS Converter"))
        self.assertIn("independent third-party project", readme)
        self.assertIn("GUZHUYAXIAN/step-to-acis-converter/releases", readme)
        self.assertNotIn("v1.0.0", readme)
        self.assertIn("Copyright (c) 2026 GUZHUYAXIAN", license_text)

    def test_production_windows_use_public_title(self) -> None:
        for name in ("gui.py", "portable_main.py"):
            source = (self.root / "src" / "step_to_acis" / name).read_text(encoding="utf-8")
            self.assertIn('root.title("STEP to ACIS Converter")', source)

    def test_public_readmes_cover_runtime_boundary(self) -> None:
        for path in (self.root / "README.md", self.root / "packaging" / "portable_README.md"):
            text = path.read_text(encoding="utf-8")
            for expected in ("Windows x64", "无需安装 Python", "环境自检", "自动扫描", "手动选择", "SpaceClaim 2022 R2", "无模型", "SHA-256", "SAB", "Skip", "ACIS V22", "Millimeters", "SmartScreen", "本地", "不上传", "没有取消或强制停止按钮", "independent third-party project"):
                with self.subTest(path=path.name, expected=expected):
                    self.assertIn(expected, text)
