import unittest

from step_to_acis.gui_models import GuiEvent, GuiRunState, reduce_gui_state


class GuiTerminalPidTests(unittest.TestCase):
    def test_completed_batch_clears_process_pid(self):
        state = GuiRunState(running=True, pid=1234)

        state = reduce_gui_state(state, GuiEvent("batch_completed", {}))

        self.assertFalse(state.running)
        self.assertIsNone(state.pid)

    def test_failed_batch_clears_process_pid(self):
        state = GuiRunState(running=True, pid=1234)

        state = reduce_gui_state(
            state, GuiEvent("batch_failed", {"error_message": "failed"})
        )

        self.assertFalse(state.running)
        self.assertIsNone(state.pid)
