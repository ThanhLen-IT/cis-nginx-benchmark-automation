"""Write real Ansible recap for the workflow's idempotence check."""
import json
import os
from pathlib import Path
from ansible.plugins.callback import CallbackBase


class CallbackModule(CallbackBase):
    CALLBACK_VERSION = 2.0
    CALLBACK_TYPE = "aggregate"
    CALLBACK_NAME = "cis_evidence"
    CALLBACK_NEEDS_ENABLED = True

    def v2_playbook_on_stats(self, stats):
        name = os.environ.get("CIS_RECAP_PATH")
        if name:
            Path(name).write_text(json.dumps({h: stats.summarize(h) for h in stats.processed}, indent=2) + "\n")
