from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from step_to_acis.gui import _TkView


class Variable:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class FileSelectionViewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.files = (self.root / "中文 a.STP", self.root / "b.step")
        for file in self.files:
            file.write_bytes(b"STEP")
        self.view = _TkView.__new__(_TkView)
        self.view.root = Mock()
        self.view._controls_enabled = True
        self.view._selected_files = None
        self.view.input_var = Variable(str(self.root))
        self.view.selection_var = Variable()
        self.view.selected_text = Mock()
        self.view.recursive_check = Mock()
        self.view.show_error = Mock()

    def choose(self, result):
        with patch("step_to_acis.gui.filedialog.askopenfilenames", return_value=result) as dialog:
            self.view.choose_step_files()
        return dialog

    def test_multiple_selection_shows_exact_names_count_and_disables_recursion(self):
        dialog = self.choose(tuple(map(str, self.files)))
        self.assertEqual(set(self.files), set(self.view.get_selected_files()))
        self.assertIn("2 个文件", self.view.selection_var.get())
        text = self.view.selected_text.insert.call_args.args[1]
        for file in self.files:
            self.assertIn(file.name, text)
        self.view.recursive_check.configure.assert_called_with(state="disabled")
        self.assertEqual(str(self.root), dialog.call_args.kwargs["initialdir"])

    def test_cancel_preserves_selection_and_clear_returns_to_scan(self):
        self.choose(tuple(map(str, self.files)))
        before = self.view.get_selected_files()
        self.choose(())
        self.assertEqual(before, self.view.get_selected_files())
        self.view.clear_file_selection()
        self.assertIsNone(self.view.get_selected_files())
        self.view.selected_text.grid_remove.assert_called_once()
        self.view.recursive_check.configure.assert_called_with(state="normal")

    def test_invalid_extension_preserves_previous_selection(self):
        self.choose((str(self.files[0]),))
        bad = self.root / "other.prt"
        bad.write_bytes(b"PRT")
        self.choose((str(bad),))
        self.assertEqual((self.files[0],), self.view.get_selected_files())
        self.view.show_error.assert_called_once()

    def test_running_batch_blocks_picker_and_clear(self):
        self.view._selected_files = self.files
        self.view._controls_enabled = False
        dialog = self.choose(())
        self.view.clear_file_selection()
        dialog.assert_not_called()
        self.assertEqual(self.files, self.view.get_selected_files())
