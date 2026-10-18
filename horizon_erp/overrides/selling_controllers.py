# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Quotation / Sales Order controllers that keep an agreed rate above the pricing-rule rate.

ERPNext v15 re-applies the pricing rules of every row on each ``validate``
(``set_missing_item_details`` -> ``apply_pricing_rule_on_items``): a row matched by a rule (e.g. the
Premium 5 % Customer Group rule) gets ``rate = price_list_rate x (1 - discount)`` whatever rate was
posted, so an Opportunity rate the customer agreed *above* that rate was silently lowered on save,
on submit and again on the Sales Order. Rows without a rule already keep a higher rate (ERPNext
stores it as an Amount margin).

The override wraps only that one method: after ERPNext applied the rules, the row's agreed rate
(Custom Field ``horizon_agreed_rate``, set from the Opportunity and mapped to the Sales Order) is put
back when it is above the resulting rate (``horizon_selling.selling.keep_agreed_rate``). Rows
without an agreed rate are priced exactly as in standard ERPNext, so discount governance
(``validate_discounts``) is unchanged.
"""

from erpnext.selling.doctype.quotation.quotation import Quotation
from erpnext.selling.doctype.sales_order.sales_order import SalesOrder

from horizon_erp.horizon_selling.selling import keep_agreed_rate


class AgreedRateMixin:
	def apply_pricing_rule_on_items(self, item, pricing_rule_args):
		super().apply_pricing_rule_on_items(item, pricing_rule_args)
		keep_agreed_rate(item, pricing_rule_args)


class HorizonQuotation(AgreedRateMixin, Quotation):
	pass


class HorizonSalesOrder(AgreedRateMixin, SalesOrder):
	pass
