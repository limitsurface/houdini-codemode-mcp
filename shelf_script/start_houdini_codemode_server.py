"""Paste this script into a Houdini Python shelf tool."""

import threading

import hou


PORT_OPTIONS = (
    ("Default port (18811)", 18811),
    ("Port 18812", 18812),
    ("Port 18813", 18813),
    ("Port 18814", 18814),
)

selection = hou.ui.displayMessage(
    "Choose the loopback port for this Houdini Code Mode instance.",
    buttons=tuple(label for label, _port in PORT_OPTIONS),
    default_choice=0,
    close_choice=-1,
    title="Start Houdini Code Mode Server",
)
if selection < 0:
    raise SystemExit

port = PORT_OPTIONS[selection][1]

try:
    import hrpyc
except ImportError as exc:
    hou.ui.displayMessage(
        "Failed to import Houdini's hrpyc module.\n\n{}".format(exc),
        severity=hou.severityType.Error,
    )
    raise

current_server = getattr(hou.session, "_houdini_codemode_server", None)
current_thread = getattr(hou.session, "_houdini_codemode_server_thread", None)
current_port = getattr(hou.session, "_houdini_codemode_server_port", None)

if current_server is not None and current_port == port:
    message = "Houdini Code Mode is already listening on 127.0.0.1:{}.".format(port)
else:
    try:
        # Construction binds the listener. Prepare the replacement before
        # stopping a working server so a busy destination does not strand the user.
        new_server = hrpyc.ThreadedServer(
            hrpyc.SlaveService,
            hostname="127.0.0.1",
            port=port,
            reuse_addr=True,
            registrar=None,
            auto_register=False,
        )
        new_server.logger.quiet = True
    except Exception as exc:
        detail = str(exc)
        if "in use" in detail.lower() or "address already in use" in detail.lower():
            message = "Port {} is already in use. Choose another port.".format(port)
        else:
            hou.ui.displayMessage(
                "Failed to prepare Houdini Code Mode on port {}.\n\n{}".format(
                    port, detail
                ),
                severity=hou.severityType.Error,
            )
            raise
    else:
        if current_server is not None:
            current_server.close()
            if current_thread is not None and current_thread.is_alive():
                current_thread.join(2.0)

        new_thread = threading.Thread(
            target=new_server.start,
            name="houdini-codemode-{}".format(port),
            daemon=True,
        )
        new_thread.start()
        hou.session._houdini_codemode_server = new_server
        hou.session._houdini_codemode_server_thread = new_thread
        hou.session._houdini_codemode_server_port = port

        if current_port is None:
            message = "Houdini Code Mode started on 127.0.0.1:{}.".format(port)
        else:
            message = "Houdini Code Mode switched from port {} to {}.".format(
                current_port, port
            )

if port != 18811:
    message += "\n\nUse instance.port={} or --port {} for this Houdini instance.".format(
        port, port
    )

hou.ui.displayMessage(message)
