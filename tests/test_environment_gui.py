from dataclasses import replace
from pathlib import Path
import queue
import unittest

from step_to_acis.environment_gui import (
    EnvironmentCheckGui,
    _TkEnvironmentView,
    render_environment_details,
)
from step_to_acis.environment_models import REQUIRED_CHECK_IDS, CheckResult, EnvironmentState


def passing_state():
    return EnvironmentState(
        checks=tuple(
            CheckResult(check_id, "required", "pass", "通过", "原因", "建议")
            for check_id in REQUIRED_CHECK_IDS
        ),
        profile_path=Path("profile.json"),
        report_path=Path("报告 目录/probe-report.json"),
    )


class FakeRoot:
    def __init__(self):
        self.after_calls = []

    def after(self, delay, callback):
        self.after_calls.append((delay, callback))


class FakeView:
    def __init__(self, root):
        self.rendered = []
        self.busy = []
        self.errors = []
        self.destroyed = False

    def bind_controller(self, controller):
        self.controller = controller

    def render(self, state):
        self.rendered.append(state)

    def set_busy(self, busy):
        self.busy.append(busy)

    def show_error(self, message):
        self.errors.append(message)

    def destroy(self):
        self.destroyed = True


class FakeThread:
    def __init__(self, *, target, daemon):
        self.target = target
        self.daemon = daemon
        self.started = False

    def start(self):
        self.started = True


class FakeController:
    def __init__(self, state):
        self.state = state
        self.calls = []

    def scan(self):
        self.calls.append("scan")
        return self.state

    def select_manual(self, path):
        self.calls.append(("manual", path))
        return self.state

    def reprobe(self):
        self.calls.append("reprobe")
        return self.state

    def rescan(self):
        self.calls.append("rescan_view")

    def browse_executable(self):
        self.calls.append("browse_view")

    def enter_converter(self):
        self.calls.append("enter_view")

    def select_candidate(self, path):
        self.calls.append(("candidate", path))
        return self.state

    def fail_closed(self, error):
        self.calls.append(("fail_closed", str(error)))
        self.state = EnvironmentState()
        return self.state


class FakeWidget:
    def __init__(self):
        self.bindings = {}
        self.configuration = {}

    def configure(self, **kwargs):
        self.configuration.update(kwargs)

    def bind(self, event, callback):
        self.bindings[event] = callback


class FakeVariable:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value


class EnvironmentGuiTests(unittest.TestCase):
    def make_gui(self, state=None, picker=None):
        root = FakeRoot()
        controller = FakeController(state or EnvironmentState())
        threads = []
        approvals = []

        def thread_factory(**kwargs):
            thread = FakeThread(**kwargs)
            threads.append(thread)
            return thread

        gui = EnvironmentCheckGui(
            root,
            controller=controller,
            on_approved=approvals.append,
            view_factory=FakeView,
            thread_factory=thread_factory,
            file_picker=picker or (lambda **kwargs: ""),
        )
        return gui, root, controller, threads, approvals

    def test_details_render_all_statuses_reason_remediation_and_report(self):
        state = EnvironmentState(
            checks=(
                CheckResult("p", "required", "pass", "通过", "通过原因", "无需处理"),
                CheckResult("w", "warning", "warning", "警告", "警告原因", "处理建议"),
                CheckResult("f", "required", "failure", "失败", "具体原因", "具体修复"),
                CheckResult("n", "required", "pending", "等待", "等待原因", "稍后重试"),
            ),
            report_path=Path("本地 报告/probe.json"),
        )

        rendered = render_environment_details(state)

        for text in ("通过", "警告", "失败", "等待", "具体原因", "具体修复", str(state.report_path)):
            self.assertIn(text, rendered)

    def test_entry_is_rechecked_and_only_approved_state_transitions(self):
        gui, _, controller, _, approvals = self.make_gui(EnvironmentState())
        gui.enter_converter()
        self.assertEqual([], approvals)
        self.assertTrue(gui.view.errors)

        controller.state = passing_state()
        gui.enter_converter()
        self.assertEqual([controller.state], approvals)

    def test_rescan_runs_on_one_daemon_worker_and_poll_updates_tk_side(self):
        gui, root, controller, threads, _ = self.make_gui(passing_state())

        gui.rescan()

        self.assertEqual([True], gui.view.busy)
        self.assertEqual(1, len(threads))
        self.assertTrue(threads[0].daemon)
        self.assertTrue(threads[0].started)
        self.assertEqual([], controller.calls)

        threads[0].target()
        self.assertEqual(["scan"], controller.calls)
        self.assertEqual(1, len(gui.view.rendered))
        gui.poll_events()
        self.assertEqual(passing_state(), gui.view.rendered[-1])
        self.assertEqual(False, gui.view.busy[-1])
        self.assertEqual(100, root.after_calls[-1][0])

    def test_manual_picker_uses_exact_spaceclaim_filter_then_worker(self):
        picker_calls = []

        def picker(**kwargs):
            picker_calls.append(kwargs)
            return r"C:\Program Files\ANSYS Inc\v222\SCDM\SpaceClaim.exe"

        gui, _, controller, threads, _ = self.make_gui(passing_state(), picker)
        gui.browse_executable()

        self.assertEqual([{"filetypes": [("SpaceClaim", "SpaceClaim.exe")]}], picker_calls)
        threads[0].target()
        self.assertEqual("manual", controller.calls[-1][0])

    def test_reprobe_is_explicit_and_busy_blocks_duplicate_actions(self):
        gui, _, controller, threads, _ = self.make_gui(passing_state())
        gui.reprobe()
        gui.rescan()

        self.assertEqual(1, len(threads))
        threads[0].target()
        gui.poll_events()
        self.assertEqual(["reprobe"], controller.calls)

    def test_candidate_selection_runs_the_same_validated_selection_path(self):
        selected = Path(r"C:\Program Files\ANSYS Inc\v222\SCDM\SpaceClaim.exe")
        gui, _, controller, threads, _ = self.make_gui(passing_state())

        gui.select_candidate(selected)
        threads[0].target()

        self.assertEqual(("manual", selected), controller.calls[-1])

    def test_candidate_combobox_is_bound_to_validated_selection(self):
        selected = r"C:\Program Files\ANSYS Inc\v222\SCDM\SpaceClaim.exe"
        controller = FakeController(passing_state())
        view = _TkEnvironmentView.__new__(_TkEnvironmentView)
        view.rescan_button = FakeWidget()
        view.manual_button = FakeWidget()
        view.reprobe_button = FakeWidget()
        view.enter_button = FakeWidget()
        view.candidate_box = FakeWidget()
        view.candidate_var = FakeVariable(selected)

        view.bind_controller(controller)
        view.candidate_box.bindings["<<ComboboxSelected>>"](None)

        self.assertEqual(("candidate", Path(selected)), controller.calls[-1])

    def test_async_error_replaces_old_authorization_with_fail_closed_state(self):
        gui, _, controller, _, _ = self.make_gui(passing_state())
        gui.event_queue.put(("error", RuntimeError("resource decode failed")))

        gui.poll_events()

        self.assertEqual(("fail_closed", "resource decode failed"), controller.calls[-1])
        self.assertFalse(gui.view.rendered[-1].can_enter_converter)
        self.assertEqual(["resource decode failed"], gui.view.errors)

    def test_destroy_hides_self_check_view_and_stops_polling(self):
        gui, root, *_ = self.make_gui()
        gui.destroy()
        gui.poll_events()
        self.assertTrue(gui.view.destroyed)
        self.assertEqual([], root.after_calls)


if __name__ == "__main__":
    unittest.main()
