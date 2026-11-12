"""Navigate the main workspace through its public controls and detail route."""


def page(app, name):
    if name in {"Portfolio", "Risk review", "Board report", "Documents & data"}:
        app.radio(key="preview_navigation").set_value(name).run()
    elif name == "User guide":
        app.button(key="workspace_help").click().run()
    elif name == "Settings":
        app.button(key="workspace_settings").click().run()
    else:
        app.session_state._preview_next_page = name
        app.run()
    assert not app.exception
    return app


def prediction_mode(app, mode):
    page(app, "Settings")
    app.selectbox(key="analysis_prediction").select(mode).run()
    next(b for b in app.button if b.label == "Back to workspace").click().run()
    assert not app.exception
