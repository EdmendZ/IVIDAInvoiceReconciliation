"""Keep unit tests independent from the developer's local workspace switch."""

import os


# Application modules create cached settings during test collection. An explicit
# process environment value takes precedence over the developer's private .env.
# Tests for the enabled workspace override the settings dependency themselves.
os.environ["WORKSPACE_ENABLED"] = "false"
os.environ["WORKSPACE_TENANT_ID"] = ""
os.environ["WORKSPACE_STORE_ID"] = ""
