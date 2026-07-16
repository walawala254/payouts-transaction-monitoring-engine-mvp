from streamlit.testing.v1 import AppTest


def test_public_demo_loads_and_runs_synthetic_monitoring():
    app = AppTest.from_file("app.py", default_timeout=60).run()
    assert not app.exception
    assert [title.value for title in app.title] == ["Monitoring Run"]

    next(button for button in app.button if button.label == "Load bundled synthetic demo").click().run()
    assert not app.exception

    next(button for button in app.button if button.label == "Run Monitoring Engine").click().run(timeout=60)
    assert not app.exception
    assert any("Monitoring run complete" in message.value for message in app.success)
