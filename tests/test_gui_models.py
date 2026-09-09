from dataclasses import replace
import unittest

from step_to_acis.gui_models import (
    GuiEvent,
    GuiFormValues,
    GuiInputError,
    GuiRunState,
    reduce_gui_state,
    validate_form_values,
)
from step_to_acis.models import ConversionResult, Status


class GuiFormValuesTests(unittest.TestCase):
    def valid_values(self):
        return GuiFormValues(
            input_dir=r"E:\中文 STEP",
            output_dir=r"E:\中文 ACIS",
            output_format="SAT",
            recursive=True,
            overwrite_policy="Overwrite",
            acis_version="V22",
            chunk_size=10,
            timeout_seconds=60.0,
            retry_count=1,
        )

    def test_valid_values_map_to_config_overrides(self):
        values = validate_form_values(self.valid_values())

        self.assertEqual(
            {
                "input_dir": r"E:\中文 STEP",
                "output_dir": r"E:\中文 ACIS",
                "output_formats": ["SAT"],
                "recursive": True,
                "overwrite_policy": "Overwrite",
                "acis_version": "V22",
                "chunk_size": 10,
                "heartbeat_timeout_seconds": 60.0,
                "retry_count": 1,
            },
            values.to_overrides(),
        )

    def test_validation_does_not_require_directories_to_exist(self):
        values = validate_form_values(self.valid_values())

        self.assertEqual(r"E:\中文 STEP", values.input_dir)

    def test_invalid_fields_raise_field_specific_errors(self):
        cases = [
            ("input_dir", "", "input_dir"),
            ("output_dir", "", "output_dir"),
            ("output_format", "DWG", "output_format"),
            ("acis_version", "V14", "acis_version"),
            ("recursive", 1, "recursive"),
            ("overwrite_policy", "Replace", "overwrite_policy"),
            ("chunk_size", 0, "chunk_size"),
            ("chunk_size", 101, "chunk_size"),
            ("timeout_seconds", 0, "timeout_seconds"),
            ("retry_count", -1, "retry_count"),
            ("retry_count", 2, "retry_count"),
        ]
        for field, value, expected in cases:
            with self.subTest(field=field, value=value):
                with self.assertRaisesRegex(GuiInputError, expected):
                    validate_form_values(replace(self.valid_values(), **{field: value}))

    def test_same_normalized_directory_is_rejected(self):
        values = replace(
            self.valid_values(),
            input_dir=r"E:\Folder\Models",
            output_dir=r"e:\folder\models\.",
        )

        with self.assertRaisesRegex(GuiInputError, "distinct"):
            validate_form_values(values)


class GuiRunStateTests(unittest.TestCase):
    @staticmethod
    def result(sequence, status):
        return ConversionResult(
            sequence=sequence,
            task_id="task-{}".format(sequence),
            source_name="{}.stp".format(sequence),
            source_path=r"E:\输入\{}.stp".format(sequence),
            output_name="{}.sab".format(sequence),
            output_path=r"E:\输出\{}.sab".format(sequence),
            output_format="SAB",
            source_size_bytes=10,
            output_size_bytes=20 if status is Status.SUCCESS else 0,
            start_time="start",
            duration_seconds=1.0,
            status=status,
            error_message="failure" if status is Status.FAILED else "",
        )

    def test_event_sequence_reduces_to_partial_failure_completion(self):
        state = GuiRunState()
        state = reduce_gui_state(state, GuiEvent("batch_started", {"total": 3}))
        self.assertTrue(state.running)
        self.assertEqual(3, state.total)

        state = reduce_gui_state(
            state,
            GuiEvent(
                "status",
                {
                    "kind": "task_started",
                    "source_path": r"E:\输入\中文.stp",
                    "pid": 1234,
                    "chunk_id": "chunk-0001",
                },
            ),
        )
        self.assertEqual("中文.stp", state.current_file)
        self.assertEqual(1234, state.pid)
        self.assertEqual("chunk-0001", state.chunk_id)

        state = reduce_gui_state(
            state,
            GuiEvent(
                "status",
                {
                    "kind": "process_finished",
                    "pid": 1234,
                    "chunk_id": "chunk-0001",
                },
            ),
        )
        self.assertIsNone(state.pid)

        for sequence, status in enumerate(
            [Status.SUCCESS, Status.FAILED, Status.SKIPPED],
            start=1,
        ):
            state = reduce_gui_state(
                state,
                GuiEvent("result", {"result": self.result(sequence, status)}),
            )
        self.assertEqual((3, 1, 1, 1), (state.completed, state.success, state.failed, state.skipped))

        state = reduce_gui_state(
            state,
            GuiEvent(
                "batch_completed",
                {"csv_path": r"E:\logs\conversion.csv", "run_log_path": r"E:\logs\run.txt"},
            ),
        )
        self.assertFalse(state.running)
        self.assertEqual("批次完成，但存在失败", state.message)
        self.assertEqual(r"E:\logs\conversion.csv", state.csv_path)
        self.assertEqual(r"E:\logs\run.txt", state.run_log_path)

    def test_zero_failure_completion_uses_success_message(self):
        state = GuiRunState(running=True, total=1, completed=1, success=1)

        state = reduce_gui_state(state, GuiEvent("batch_completed", {}))

        self.assertFalse(state.running)
        self.assertEqual("批次转换完成", state.message)

    def test_batch_failed_clears_running_and_stores_fatal_message(self):
        state = GuiRunState(running=True)

        state = reduce_gui_state(
            state,
            GuiEvent("batch_failed", {"error_message": "controller failed"}),
        )

        self.assertFalse(state.running)
        self.assertEqual("controller failed", state.fatal_error)
        self.assertEqual("controller failed", state.message)

    def test_unknown_event_leaves_state_unchanged(self):
        state = GuiRunState(total=3, message="unchanged")

        reduced = reduce_gui_state(state, GuiEvent("future_event", {"value": 1}))

        self.assertIs(state, reduced)


if __name__ == "__main__":
    unittest.main()
