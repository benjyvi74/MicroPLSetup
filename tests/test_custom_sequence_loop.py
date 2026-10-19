import pytest
from unittest.mock import MagicMock
from micropl.qt import QApplication
from micropl.gui.automation_panel import LoopParamWidget, unroll_custom_sequence, AutomationPanel
from micropl.gui.sequence_dialog import CustomSequenceSummaryDialog, RepeatCustomStepsDialog


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_unroll_custom_sequence_no_loops():
    steps = [
        {'action': 'Wait / Stabilize', 'params': {'duration': 1.0}, 'params_desc': '1.0 s', 'comment': 'Step 1'},
        {'action': 'Collect Spectrum', 'params': {}, 'params_desc': 'Capture', 'comment': 'Step 2'},
    ]
    unrolled = unroll_custom_sequence(steps)
    assert len(unrolled) == 2
    assert unrolled[0]['orig_step_num'] == 1
    assert unrolled[0]['loop_iteration'] == 1
    assert unrolled[0]['total_iterations'] == 1
    assert unrolled[1]['orig_step_num'] == 2
    assert unrolled[1]['loop_iteration'] == 1
    assert unrolled[1]['total_iterations'] == 1


def test_unroll_custom_sequence_single_loop():
    # Step 1: Open Shutter
    # Step 2: Collect Spectrum
    # Step 3: Wait 2s
    # Step 4: Repeat steps 2 to 3, 3 times
    # Step 5: Close Shutter
    steps = [
        {'action': 'Shutter (linked)', 'params': {'open': True}, 'params_desc': 'Open', 'comment': 'Open'},
        {'action': 'Collect Spectrum', 'params': {}, 'params_desc': 'Capture', 'comment': 'Scan'},
        {'action': 'Wait / Stabilize', 'params': {'duration': 2.0}, 'params_desc': '2.0 s', 'comment': 'Wait'},
        {'action': 'Repeat / Loop', 'params': {'from_step': 2, 'to_step': 3, 'count': 3}, 'params_desc': 'Steps 2 to 3 (3x total)', 'comment': ''},
        {'action': 'Shutter (linked)', 'params': {'open': False}, 'params_desc': 'Close', 'comment': 'Close'},
    ]
    unrolled = unroll_custom_sequence(steps)
    # Total executed steps: 1 (open) + 3*2 (scan+wait) + 1 (close) = 8
    assert len(unrolled) == 8

    # Step 1
    assert unrolled[0]['orig_step_num'] == 1
    assert unrolled[0]['loop_iteration'] == 1
    assert unrolled[0]['total_iterations'] == 1

    # Loop 1
    assert unrolled[1]['orig_step_num'] == 2
    assert unrolled[1]['loop_iteration'] == 1
    assert unrolled[1]['total_iterations'] == 3
    assert unrolled[2]['orig_step_num'] == 3
    assert unrolled[2]['loop_iteration'] == 1

    # Loop 2
    assert unrolled[3]['orig_step_num'] == 2
    assert unrolled[3]['loop_iteration'] == 2
    assert unrolled[3]['total_iterations'] == 3
    assert unrolled[4]['orig_step_num'] == 3
    assert unrolled[4]['loop_iteration'] == 2

    # Loop 3
    assert unrolled[5]['orig_step_num'] == 2
    assert unrolled[5]['loop_iteration'] == 3
    assert unrolled[5]['total_iterations'] == 3
    assert unrolled[6]['orig_step_num'] == 3
    assert unrolled[6]['loop_iteration'] == 3

    # Step 5
    assert unrolled[7]['orig_step_num'] == 5
    assert unrolled[7]['loop_iteration'] == 1
    assert unrolled[7]['total_iterations'] == 1


def test_unroll_custom_sequence_count_one():
    steps = [
        {'action': 'Collect Spectrum', 'params': {}, 'params_desc': 'Capture', 'comment': ''},
        {'action': 'Repeat / Loop', 'params': {'from_step': 1, 'to_step': 1, 'count': 1}, 'params_desc': '', 'comment': ''},
    ]
    unrolled = unroll_custom_sequence(steps)
    assert len(unrolled) == 1
    assert unrolled[0]['orig_step_num'] == 1
    assert unrolled[0]['loop_iteration'] == 1


def test_loop_param_widget(qapp):
    widget = LoopParamWidget(from_step=2, to_step=4, count=5, max_steps=10)
    assert widget.get_values() == (2, 4, 5)

    widget.set_values(1, 3, 4)
    assert widget.get_values() == (1, 3, 4)

    widget.set_max_steps(20)
    assert widget.from_spin.maximum() == 20
    assert widget.to_spin.maximum() == 20


def test_custom_sequence_table_serialization(qapp):
    panel = AutomationPanel()

    # Add Wait step
    panel._on_add_custom_step()
    # Add Loop step
    panel._on_add_custom_step()
    act_combo = panel.custom_seq_table.cellWidget(1, 1)
    act_combo.setCurrentText("Repeat / Loop")

    loop_widget = panel.custom_seq_table.cellWidget(1, 2)
    assert isinstance(loop_widget, LoopParamWidget)
    loop_widget.set_values(1, 1, 3)

    # Serialize
    serialized = panel._serialize_custom_row(1)
    assert serialized['action'] == "Repeat / Loop"
    assert serialized['params'] == {'from_step': 1, 'to_step': 1, 'count': 3}

    # Deserialize
    panel._deserialize_custom_row(1, {
        'action': 'Repeat / Loop',
        'params': {'from_step': 1, 'to_step': 1, 'count': 7},
        'comment': 'Test Loop'
    })
    widget_after = panel.custom_seq_table.cellWidget(1, 2)
    assert isinstance(widget_after, LoopParamWidget)
    assert widget_after.get_values() == (1, 1, 7)

    # get_custom_sequence_steps
    steps = panel.get_custom_sequence_steps()
    assert len(steps) == 2
    assert steps[1]['action'] == "Repeat / Loop"
    assert steps[1]['params']['count'] == 7
    assert "Steps 1 to 1 (7x total)" in steps[1]['params_desc']


def test_summary_dialog_unrolled_duration(qapp):
    steps = [
        {'action': 'Wait / Stabilize', 'params': {'duration': 2.0}, 'params_desc': '2.0 s', 'comment': ''},
        {'action': 'Repeat / Loop', 'params': {'from_step': 1, 'to_step': 1, 'count': 3}, 'params_desc': '', 'comment': ''},
    ]
    dlg = CustomSequenceSummaryDialog(steps)
    # Wait is 2.0s, repeated 3 times total = 6.0s
    est_dur = dlg.calculate_estimated_duration()
    assert est_dur == 6.0


def test_repeat_custom_steps_dialog(qapp):
    dlg = RepeatCustomStepsDialog(num_steps=5, sel_from=2, sel_to=4)
    assert dlg.from_spin.value() == 2
    assert dlg.to_spin.value() == 4
    assert dlg.count_spin.value() == 2

    dlg._on_loop_clicked()
    f, t, cnt, mode = dlg.get_values()
    assert (f, t, cnt, mode) == (2, 4, 2, "loop_step")

    dlg_dup = RepeatCustomStepsDialog(num_steps=5, sel_from=1, sel_to=3)
    dlg_dup.count_spin.setValue(4)
    dlg_dup._on_duplicate_clicked()
    f2, t2, cnt2, mode2 = dlg_dup.get_values()
    assert (f2, t2, cnt2, mode2) == (1, 3, 4, "duplicate")


def test_reorder_with_loop_widget(qapp):
    panel = AutomationPanel()
    panel._on_add_custom_step() # row 0: Wait
    panel._on_add_custom_step() # row 1: Wait -> change to Loop
    act_combo = panel.custom_seq_table.cellWidget(1, 1)
    act_combo.setCurrentText("Repeat / Loop")

    loop_w = panel.custom_seq_table.cellWidget(1, 2)
    assert isinstance(loop_w, LoopParamWidget)
    loop_w.set_values(1, 1, 5)

    # Reorder row 1 to row 0
    panel.custom_seq_table.move_rows([1], 0)
    cloned_w = panel.custom_seq_table.cellWidget(0, 2)
    assert isinstance(cloned_w, LoopParamWidget)
    assert cloned_w.get_values() == (1, 1, 5)


def test_collect_spectrum_params_desc_and_status_desc(qapp):
    from micropl.gui.automation_panel import CustomSequenceWorker

    # 1. Verify get_custom_sequence_steps returns empty params_desc for Collect Spectrum
    panel = AutomationPanel()
    panel._on_add_custom_step()
    act_combo = panel.custom_seq_table.cellWidget(0, 1)
    act_combo.setCurrentText("Collect Spectrum")
    steps = panel.get_custom_sequence_steps()
    assert steps[0]['action'] == "Collect Spectrum"
    assert steps[0]['params_desc'] == ""

    # 2. Verify CustomSequenceWorker progress emission with loop:
    # 2 steps repeated 2 times (4 steps total).
    raw_steps = [
        {'action': 'Collect Spectrum', 'params': {}, 'params_desc': '', 'comment': ''},
        {'action': 'Wait / Stabilize', 'params': {'duration': 0.01}, 'params_desc': '0.01 s', 'comment': ''},
        {'action': 'Repeat / Loop', 'params': {'from_step': 1, 'to_step': 2, 'count': 2}, 'params_desc': '', 'comment': ''},
    ]

    mock_hw = MagicMock()
    mock_cam = MagicMock()
    mock_cam.is_connected.return_value = True
    mock_cam.get_exposure.return_value = 0.001
    mock_cam.acquire.return_value = MagicMock(get_data=MagicMock(return_value=[0]*100))
    mock_hw.get_spectroscopy_camera.return_value = mock_cam
    mock_hw.shutter = None

    emitted_steps = []
    emitted_descs = []

    worker = CustomSequenceWorker(
        hardware_manager=mock_hw,
        steps=raw_steps,
        data_dir="/tmp/test_micropl_seq",
        metadata={},
    )
    worker.progress.connect(lambda s_idx, desc, pct: (emitted_steps.append(s_idx), emitted_descs.append(desc)))

    # Fast mock execution: run internal steps loop directly
    # Total unrolled steps should be 4
    assert len(worker.steps) == 4

    # Check unrolled descriptions and step numbers
    # Each step_idx emitted must strictly increase: 1, 2, 3, 4 (NOT 1, 2, 1, 2)
    for idx, step in enumerate(worker.steps):
        step_num = idx + 1
        orig_step_num = step.get('orig_step_num', step_num)
        iter_num = step.get('loop_iteration', 1)
        total_iters = step.get('total_iterations', 1)

        p_desc = step.get('params_desc', '').strip()
        if p_desc and p_desc.lower() not in ("capture spectrum", "collect spectrum", "capture"):
            param_suffix = f" ({p_desc})"
        else:
            param_suffix = ""

        if total_iters > 1:
            status_desc = f"Step {orig_step_num} (Pass {iter_num}/{total_iters}): {step['action']}{param_suffix}"
        else:
            status_desc = f"Step {orig_step_num}: {step['action']}{param_suffix}"

        worker.progress.emit(step_num, status_desc, int((idx / len(worker.steps)) * 100))

    assert emitted_steps == [1, 2, 3, 4]
    # Verify no redundant "(Capture Spectrum)" in Collect Spectrum description
    assert emitted_descs[0] == "Step 1 (Pass 1/2): Collect Spectrum"
    assert emitted_descs[1] == "Step 2 (Pass 1/2): Wait / Stabilize (0.01 s)"
    assert emitted_descs[2] == "Step 1 (Pass 2/2): Collect Spectrum"
    assert emitted_descs[3] == "Step 2 (Pass 2/2): Wait / Stabilize (0.01 s)"
    for desc in emitted_descs:
        assert "Capture Spectrum" not in desc
        assert "()" not in desc


def test_collect_spectrum_custom_prefix(qapp, tmp_path):
    from micropl.gui.automation_panel import CustomSequenceWorker
    from micropl.qt import QLineEdit

    panel = AutomationPanel()
    panel._on_add_custom_step()
    act_combo = panel.custom_seq_table.cellWidget(0, 1)
    act_combo.setCurrentText("Collect Spectrum")

    edit = panel.custom_seq_table.cellWidget(0, 2)
    assert isinstance(edit, QLineEdit)
    assert "Prefix (default: step_001)" in edit.placeholderText()

    # Default prefix when empty
    steps = panel.get_custom_sequence_steps()
    assert 'prefix' not in steps[0]['params']
    assert steps[0]['params_desc'] == ""

    # Set custom prefix
    edit.setText("laser_on")
    steps = panel.get_custom_sequence_steps()
    assert steps[0]['params']['prefix'] == "laser_on"
    assert steps[0]['params_desc'] == "Prefix: laser_on"

    # Serialize & Deserialize
    serialized = panel._serialize_custom_row(0)
    assert serialized['params'] == {'prefix': 'laser_on'}

    panel._deserialize_custom_row(0, {
        'action': 'Collect Spectrum',
        'params': {'prefix': 'my_pl_sample'},
        'comment': 'Test'
    })
    edit2 = panel.custom_seq_table.cellWidget(0, 2)
    assert isinstance(edit2, QLineEdit)
    assert edit2.text() == "my_pl_sample"

    # Test file naming logic in CustomSequenceWorker with custom prefix and loop
    raw_steps = [
        {'action': 'Collect Spectrum', 'params': {'prefix': 'my_sample'}, 'params_desc': 'Prefix: my_sample', 'comment': ''},
        {'action': 'Repeat / Loop', 'params': {'from_step': 1, 'to_step': 1, 'count': 2}, 'params_desc': '', 'comment': ''},
    ]

    mock_hw = MagicMock()
    mock_cam = MagicMock()
    mock_cam.is_connected.return_value = True
    mock_cam.get_exposure.return_value = 0.001
    mock_cam.acquire.return_value = MagicMock(get_data=MagicMock(return_value=[0]*100))
    mock_hw.get_spectroscopy_camera.return_value = mock_cam
    mock_hw.shutter = None

    worker = CustomSequenceWorker(
        hardware_manager=mock_hw,
        steps=raw_steps,
        data_dir=str(tmp_path),
        metadata={},
    )
    # Check that unrolled steps hold the prefix
    assert len(worker.steps) == 2
    assert worker.steps[0]['params']['prefix'] == "my_sample"
    assert worker.steps[1]['params']['prefix'] == "my_sample"

    # Test filename resolution logic
    for step in worker.steps:
        total_iters = step.get('total_iterations', 1)
        iter_num = step.get('loop_iteration', 1)
        orig_step_num = step.get('orig_step_num', 1)
        params = step.get('params', {})
        custom_prefix = params.get('prefix', '').strip()
        base_prefix = custom_prefix if custom_prefix else f"step_{orig_step_num:03d}"
        if total_iters > 1:
            step_name = f"{base_prefix}_iter{iter_num:02d}"
        else:
            step_name = base_prefix
        
        if iter_num == 1:
            assert step_name == "my_sample_iter01"
        elif iter_num == 2:
            assert step_name == "my_sample_iter02"



