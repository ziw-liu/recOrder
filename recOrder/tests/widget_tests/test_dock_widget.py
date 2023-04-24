from recOrder.plugin.main_widget import MainWidget


def test_dock_widget(make_napari_viewer):
    viewer = make_napari_viewer()
    assert viewer
