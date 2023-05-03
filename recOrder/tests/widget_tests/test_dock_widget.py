import os
import warnings


def test_dock_widget(make_napari_viewer):
    display = os.environ.get("DISPLAY")
    if display:
        warnings.warn(f"DISPLAY: {display}")
    viewer = make_napari_viewer()
    assert viewer
