"""
Config file for jupyter
"""

import os

c = get_config()  # noqa: F821 pylint: disable=undefined-variable

jupyter_server_port = int(os.getenv("JUPYTER_SERVER_PORT"))

# http connection config
c.NotebookApp.ip = "0.0.0.0"
c.NotebookApp.port = jupyter_server_port
c.NotebookApp.root_dir = "/workspace"
c.NotebookApp.allow_root = True
c.NotebookApp.port_retries = 0
c.NotebookApp.quit_button = False
c.NotebookApp.allow_remote_access = True
c.NotebookApp.disable_check_xsrf = True
c.NotebookApp.allow_origin = "*"
c.NotebookApp.trust_xheaders = True

# ensure that Jupyter doesn't open a browser window on image startup
c.NotebookApp.open_browser = False
c.LabApp.open_browser = False
c.ServerApp.open_browser = False
c.ExtensionApp.open_browser = False

# set base url if available
base_url = "/" + os.getenv("MAIN_USER", "")
if base_url is not None and base_url != "/":
    c.NotebookApp.base_url = base_url

# delete files fully when deleted
c.FileContentsManager.delete_to_trash = False

# deactivate token -> no authentication
c.NotebookApp.token = ""
