DocType controller overrides referenced by `override_doctype_class` in hooks.py (kaynes convention).

`selling_controllers.py`: `HorizonQuotation` / `HorizonSalesOrder` subclass the ERPNext controllers and wrap only `apply_pricing_rule_on_items`, so a rate agreed above the pricing-rule rate (Opportunity rate, customer-agreed Item Price) is not lowered by the pricing rules on every save (ADR-18). Everything else on these DocTypes is extended through `doc_events`.

`desktop.py` is the one framework override: `override_whitelisted_methods` + `extend_bootinfo` targets that open a Horizon workspace for users holding one of its roles. Frappe otherwise requires the workspace's module to own a DocType the user can read, which most Horizon modules do not.
