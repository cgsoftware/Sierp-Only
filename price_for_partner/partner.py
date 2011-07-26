# -*- encoding: utf-8 -*-

import math

from osv import fields,osv
import tools
import ir
import pooler
from tools.translate import _

class res_partner(osv.osv):
    _inherit='res.partner'
    _columns = {
		'street': fields.related('address', 'street', type='char', string='Street'),
                'priceforpartner': fields.one2many('product.pricelist.item', 'partner_id', 'partner_id'),
                }
                
 

res_partner()

