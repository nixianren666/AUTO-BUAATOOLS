"""Presentation events for minimized/tray windows; never detect occlusion or hide UI."""
import sys


class RenderState:
    """Publish real window-state transitions once, including reentrant callbacks."""
    def __init__(self):
        self.last = None

    def update(self, shown, minimized, publish, *, force=False):
        state = (False, 'tray') if not shown else (False, 'minimized') if minimized else (True, 'visible')
        if self.last == state and not force:
            return False
        self.last = state  # Mark before callbacks to prevent a native event feeding back.
        try:
            publish(*state)
        except Exception:
            self.last = None
            return False
        return True


def install_render_lifecycle(window):
    """Read Form state on its UI thread without changing native/page visibility."""
    state = {'driver': None}
    if sys.platform != 'win32':
        return state

    def attach():
        try:
            from System import Action
            native = window.native

            def on_ui():
                try:
                    if native.IsDisposed:
                        return
                    if state['driver'] is not None:
                        state['driver']['refresh'](force=True)
                        return
                    from System.Windows.Forms import FormWindowState
                    gate = RenderState()
                    driver = {'closed': False, 'refresh': None}

                    def refresh(*_, force=False):
                        if driver['closed'] or native.IsDisposed:
                            return
                        try:
                            core = native.browser.webview.CoreWebView2
                            if core is None:
                                return

                            def publish(visible, reason):
                                core.ExecuteScriptAsync('window.BUAARenderLifecycle?.setNativeVisible('
                                                        + ('true' if visible else 'false') + ',"' + reason + '")')
                            gate.update(bool(native.Visible), native.WindowState == FormWindowState.Minimized,
                                        publish, force=force)
                        except Exception:
                            pass  # Rendering hints cannot hide or disable the interface.

                    def loaded(*_):
                        refresh(force=True)

                    def closed(*_):
                        driver['closed'] = True

                    driver['refresh'] = refresh
                    state['driver'] = driver
                    native.VisibleChanged += refresh
                    native.Resize += refresh
                    native.FormClosed += closed
                    native.browser.webview.CoreWebView2InitializationCompleted += loaded
                    refresh()
                except Exception:
                    pass

            native.BeginInvoke(Action(on_ui))
        except Exception:
            pass

    window.events.before_show += attach
    window.events.loaded += attach
    return state
