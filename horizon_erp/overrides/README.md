DocType controller overrides referenced by `override_doctype_class` in hooks.py (kaynes convention). Empty today: Horizon extends standard DocTypes through `doc_events` only.

`desktop.py` is the one framework override: `override_whitelisted_methods` + `extend_bootinfo` targets that open a Horizon workspace for users holding one of its roles. Frappe otherwise requires the workspace's module to own a DocType the user can read, which most Horizon modules do not.
