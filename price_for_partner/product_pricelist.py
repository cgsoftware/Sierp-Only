# -*- encoding: utf-8 -*-
##############################################################################
#
#    OpenERP, Open Source Management Solution
#    Copyright (C) 2004-2008 Tiny SPRL (<http://tiny.be>). All Rights Reserved
#    $Id$
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################

from osv import fields, osv
from osv.osv import except_osv
import time
from tools.translate import _
import decimal_precision as dp

def rounding(f, r):
    if not r:
        return f
    return round(f / r) * r

#
# Dimensions Definition
#

class product_pricelist(osv.osv):
    _inherit = "product.pricelist"

    def price_get_multi(self, cr, uid, pricelist_ids, products_by_qty_by_partner, context=None):
        """multi products 'price_get'.
           @param pricelist_ids:
           @param products_by_qty:
           @param partner:
           @param context: {
             'date': Date of the pricelist (%Y-%m-%d),}
           @return: a dict of dict with product_id as key and a dict 'price by pricelist' as value
        """

        def _create_parent_category_list(id, lst):
            if not id:
                return []
            parent = product_category_tree.get(id)
            if parent:
                lst.append(parent)
                return _create_parent_category_list(parent, lst)
            else:
                return lst
        # _create_parent_category_list

        if context is None:
            context = {}

        date = time.strftime('%Y-%m-%d')
        if 'date' in context:
            date = context['date']

        currency_obj = self.pool.get('res.currency')
        product_obj = self.pool.get('product.product')
        product_category_obj = self.pool.get('product.category')
        product_uom_obj = self.pool.get('product.uom')
        supplierinfo_obj = self.pool.get('product.supplierinfo')
        price_type_obj = self.pool.get('product.price.type')
        product_pricelist_version_obj = self.pool.get('product.pricelist.version')

        # product.pricelist.version:
        if pricelist_ids:
            pricelist_version_ids = pricelist_ids
        else:
            # all pricelists:
            pricelist_version_ids = product_pricelist_version_obj.search(cr, uid, [])

        pricelist_version_ids = list(set(pricelist_version_ids))

        plversions_search_args = [
            ('pricelist_id', 'in', pricelist_version_ids),
            '|',
            ('date_start', '=', False),
            ('date_start', '<=', date),
            '|',
            ('date_end', '=', False),
            ('date_end', '>=', date),
        ]
        # cerca tutte le versioni dei listini attivi
        plversion_ids = product_pricelist_version_obj.search(cr, uid, plversions_search_args)
        if len(pricelist_version_ids) != len(plversion_ids):
            msg = "At least one pricelist has no active version !\nPlease create or activate one."
            raise osv.except_osv(_('Warning !'), _(msg))

        # product.product:
        product_ids = [i[0] for i in products_by_qty_by_partner]
        products = dict([(item['id'], item) for item in product_obj.read(cr, uid, product_ids, ['categ_id', 'product_tmpl_id', 'uos_id', 'uom_id'])])
        products = product_obj.browse(cr, uid, product_ids, context=context)
        products_dict = dict([(item.id, item) for item in products])
        
        # product.category:
        product_category_ids = product_category_obj.search(cr, uid, [])
        product_categories = product_category_obj.read(cr, uid, product_category_ids, ['parent_id'])
        product_category_tree = dict([(item['id'], item['parent_id'][0]) for item in product_categories if item['parent_id']])

        results = {}
        for product_id, qty, partner in products_by_qty_by_partner:
            for pricelist_id in pricelist_version_ids:
                price = False

                tmpl_id = products_dict[product_id].product_tmpl_id and products_dict[product_id].product_tmpl_id.id or False

                categ_id = products_dict[product_id].categ_id and products_dict[product_id].categ_id.id or False
                categ_ids = _create_parent_category_list(categ_id, [categ_id])
                if categ_ids:
                    categ_where = '(categ_id IN (' + ','.join(map(str, categ_ids)) + '))'
                else:
                    categ_where = '(categ_id IS NULL)'

                cr.execute(
                    'SELECT i.*, pl.currency_id '
                    'FROM product_pricelist_item AS i, '
                        'product_pricelist_version AS v, product_pricelist AS pl '
                    'WHERE (product_tmpl_id IS NULL OR product_tmpl_id = %s) '
                        'AND (product_id IS NULL OR product_id = %s) '
                        'AND (' + categ_where + ' OR (categ_id IS NULL)) '
                        'AND price_version_id = %s '
                        'AND (min_quantity IS NULL OR min_quantity <= %s) '
                        'AND i.price_version_id = v.id AND v.pricelist_id = pl.id '
                    'ORDER BY sequence',
                    (tmpl_id, product_id, plversion_ids[0], qty))
                res1 = cr.dictfetchall()
                #import pdb;pdb.set_trace()
                uom_price_already_computed = False
                #ho tutte le righe potenziamente utili per il calcolo del prezzo
                res1 = self.priority_rules(cr, uid, res1, product_id, partner, context)
                price_item_id = 0
                for res in res1:
                    #import pdb;pdb.set_trace()
                    if res:
                        if res['base'] == -1:
                            if not res['base_pricelist_id']:
                                price = 0.0
                            else:
                                price_tmp = self.price_get(cr, uid,
                                        [res['base_pricelist_id']], product_id,
                                        qty, context=context)[res['base_pricelist_id']]
                                ptype_src = self.browse(cr, uid, res['base_pricelist_id']).currency_id.id
                                price = currency_obj.compute(cr, uid, ptype_src, res['currency_id'], price_tmp, round=False)
                                price_item_id = res['id']
                        elif res['base'] == -2:
                            # this section could be improved by moving the queries outside the loop:
                            where = []
                            if partner:
                                where = [('name', '=', partner) ]
                            sinfo = supplierinfo_obj.search(cr, uid,
                                    [('product_id', '=', tmpl_id)] + where)
                            price = 0.0
                            if sinfo:
                                qty_in_product_uom = qty
                                product_default_uom = product_obj.read(cr, uid, [tmpl_id], ['uom_id'])[0]['uom_id'][0]
                                seller_uom = supplierinfo_obj.read(cr, uid, sinfo, ['product_uom'])[0]['product_uom'][0]
                                if seller_uom and product_default_uom and product_default_uom != seller_uom:
                                    uom_price_already_computed = True
                                    qty_in_product_uom = product_uom_obj._compute_qty(cr, uid, product_default_uom, qty, to_uom_id=seller_uom)
                                cr.execute('SELECT * ' \
                                        'FROM pricelist_partnerinfo ' \
                                        'WHERE suppinfo_id IN %s' \
                                            'AND min_quantity <= %s ' \
                                        'ORDER BY min_quantity DESC LIMIT 1', (tuple(sinfo), qty_in_product_uom,))
                                res2 = cr.dictfetchone()
                                if res2:
                                    price = res2['price']
                                    price_item_id = res['id']
                        else:
                            price_type = price_type_obj.browse(cr, uid, int(res['base']))
                            price = currency_obj.compute(cr, uid,
                                    price_type.currency_id.id, res['currency_id'],
                                    product_obj.price_get(cr, uid, [product_id],
                                        price_type.field)[product_id], round=False, context=context)
                            price_item_id = res['id']

                        if price:
                            price_limit = price
                            price = price * (1.0 + (res['price_discount'] or 0.0))
                            price = rounding(price, res['price_round'])
                            price += (res['price_surcharge'] or 0.0)
                            if res['price_min_margin']:
                                price = max(price, price_limit + res['price_min_margin'])
                            if res['price_max_margin']:
                                price = min(price, price_limit + res['price_max_margin'])
                            break

                    else:
                        # False means no valid line found ! But we may not raise an
                        # exception here because it breaks the search
                        price = False

                if price:
                    if 'uom' in context and not uom_price_already_computed:
                        product = products_dict[product_id]
                        uom = product.uos_id or product.uom_id
                        price = self.pool.get('product.uom')._compute_price(cr, uid, uom.id, price, context['uom'])

                if results.get(product_id):
                    results[product_id][pricelist_id] = price
                    results[product_id]['price_item_id'] = price_item_id
                else:
                    results[product_id] = {pricelist_id: price, 'price_item_id':price_item_id}

        return results
    
    def priority_rules(self, cr, uid, righe, product_id, partner_id, context):
          
        risultati = []
        product_obj = self.pool.get('product.product')
        product = product_obj.read(cr, uid, product_id, ['categ_id'])
        categ_id = product['categ_id'][0]
        for riga in righe:      
            if riga['product_id'] == product_id and riga['partner_id'] == partner_id:
                # ha trovato la riga con articolo e cliente o fornitore
                risultati.append(riga)     
        if len(risultati) == 0:
             for riga in righe:
                # import pdb;pdb.set_trace()
                price_item = self.pool.get('product.pricelist.item').browse(cr, uid, [ riga['id']])[0]
                if price_item.categ_id:
                    #import pdb;pdb.set_trace()
                    for categ in price_item.categ_id: 
                        if categ.id == categ_id and riga['partner_id'] == partner_id:
                            #import pdb;pdb.set_trace()
                            # ha trovato la riga con categoria e cliente o fornitore
                            risultati.append(riga)     
        if len(risultati) == 0:
            #prende la riga di definizione generale del cliente
            for riga in righe:
                if riga['partner_id'] == partner_id:                    
                    price_item = self.pool.get('product.pricelist.item').browse(cr, uid, [ riga['id']])[0]
                    if not price_item.categ_id:
                            risultati.append(riga)
  
        if len(risultati) == 0:
            for riga in righe:
                if riga['product_id'] == product_id:
                # ha trovato la riga con los stesso codice articolo
                    risultati.append(riga) 
        if len(risultati) == 0:
            for riga in righe:
                price_item = self.pool.get('product.pricelist.item').browse(cr, uid, [ riga['id']])[0]
                if price_item.categ_id:
                    #import pdb;pdb.set_trace()
                    for categ in price_item.categ_id:                
                        if categ.id == categ_id:
                            # ha trovato la riga con la stessa categoria 
                            risultati.append(riga)   
        if len(risultati) == 0:
             # CERCA UNA RIGA DI DEFAULT CIOÈ SENZA ARTICOLO/CATEGORIA/CLIENTE
             for riga in righe:
                price_item = self.pool.get('product.pricelist.item').browse(cr, uid, [ riga['id']])[0]
                if price_item.categ_id:
                    #import pdb;pdb.set_trace()
                    for categ in price_item.categ_id:                  
                        if categ.id == None and riga['partner_id'] == None and riga['product_id'] == None:
                            risultati.append(riga)                                                                
        if len(risultati) == 0:
            risultati = righe
            
        #import pdb;pdb.set_trace()
        return risultati
    
product_pricelist()




class  product_pricelist_item(osv.osv):
    _inherit = "product.pricelist.item"

    def Calcolo_Sconto(self, cr, uid, ids, value, context=None):
        #import pdb;pdb.set_trace()
        if value:
            lista_sconti = value.split("+")
            sconto = float(100)
            for scontoStr in lista_sconti:
                if scontoStr <> "+":
                    sconto = sconto - (sconto * float(scontoStr) / 100)
            sconto = ((100 - sconto) * -1) / 100
        else:
            sconto = 0
        return  {'value': {'price_discount': sconto}}

    _columns = {
        'partner_id': fields.many2one('res.partner', 'Partner', ondelete='cascade', help="Inserisci l'eventuale cliente/fornitore"),
        "string_discount" : fields.char("Stringa Sconto", size=20, required=False, translate=False, help="Inserire una stringa sconto tipo:50+10+5"),
        'categ_id': fields.many2many('product.category', 'product_pricelist_item_product_category_rel', 'itemlist_id', 'categ_id', 'Categorie',),
         }
    
product_pricelist_item()


class sale_order_line(osv.osv):
    _inherit = "sale.order.line"
    
    def Calcolo_Sconto(self, cr, uid, ids, value, context=None):
        #import pdb;pdb.set_trace()
        if value:
            lista_sconti = value.split("+")
            sconto = float(100)
            for scontoStr in lista_sconti:
                if scontoStr <> "+":
                    sconto = sconto - (sconto * float(scontoStr) / 100)
            sconto = (100 - sconto)
        else:
            sconto = 0
        return  {'value': {'discount': sconto}}

    _columns = {
                "string_discount" : fields.char("Stringa Sconto", size=20, required=False, translate=True, help="Inserire una stringa sconto tipo:50+10+5"),
                
                }
    
sale_order_line()

