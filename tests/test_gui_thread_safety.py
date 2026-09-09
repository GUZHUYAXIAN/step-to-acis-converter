import unittest

from tests.test_gui_worker import ConverterGuiWorkerTests


class GuiThreadSafetyTests(ConverterGuiWorkerTests):
    def test_worker_uses_main_thread_form_snapshot_without_reading_view(self):
        calls = []

        def runner(request, reporter):
            calls.append(request)
            return self.success_outcome()

        gui, _, threads = self.make_worker_gui(runner)
        gui.start_conversion()
        self.assertEqual(1, len(threads))

        def reject_worker_view_access():
            raise AssertionError("worker touched Tk view")

        gui.view.get_form_values = reject_worker_view_access
        threads[0].target()

        self.assertEqual(1, len(calls))
        self.assertEqual(["SAB"], calls[0].overrides["output_formats"])


if __name__ == "__main__":
    unittest.main()
