import os
import re
import sys
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from fastapi import Depends, FastAPI, HTTPException
from pydantic import Field
from starlette.middleware.cors import CORSMiddleware

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import server as legacy  # noqa: E402


db = legacy.db


class TxnBody(legacy.TxnBody):
    pengambil: str = ''


class SJStatusBody(legacy.SJStatusBody):
    status: str = Field(min_length=1)


def loading_unit_from_products(products: List[dict]) -> tuple[str, str]:
    labels = []
    for prod in products:
        location = str(prod.get('location') or '').strip()
        if location and location not in labels:
            labels.append(location)
    label = ' / '.join(labels) if labels else '-'
    first = labels[0] if labels else ''
    match = re.search(r'unit\s*0*(\d+)', first, re.IGNORECASE)
    if not match:
        match = re.search(r'\b(\d{1,3})\b', first)
    prefix = match.group(1) if match else '00'
    return label, prefix


async def reserved_qty(product_id: str, kondisi: str) -> float:
    total = 0.0
    cursor = db.surat_jalan.find(
        {
            'stock_committed': False,
            'status': {'$in': ['Menunggu', 'Sedang Dimuat']},
            'kondisi': kondisi,
            'items.productId': product_id,
        },
        {'_id': 0, 'items': 1},
    )
    async for doc in cursor:
        for item in doc.get('items', []):
            if item.get('productId') == product_id:
                total += float(item.get('qty') or 0)
    return total


async def create_outgoing_transaction(body: TxnBody, user: dict):
    if body.kondisi not in ('BAIK', 'RUSAK'):
        raise HTTPException(status_code=400, detail='Kondisi stok tidak valid')
    if not body.items:
        raise HTTPException(status_code=400, detail='Pilih minimal satu produk')
    if not body.party.strip():
        raise HTTPException(status_code=400, detail='Tujuan / penerima wajib diisi')

    products_by_id = {}
    requested = defaultdict(float)
    ordered_products = []
    for item in body.items:
        requested[item.productId] += float(item.qty)
        if item.productId not in products_by_id:
            prod = await db.products.find_one({'id': item.productId}, {'_id': 0})
            if not prod:
                raise HTTPException(status_code=404, detail='Produk tidak ditemukan')
            products_by_id[item.productId] = prod
        ordered_products.append(products_by_id[item.productId])

    stock_field = 'damaged' if body.kondisi == 'RUSAK' else 'stock'
    for product_id, qty in requested.items():
        prod = products_by_id[product_id]
        current_stock = float(prod.get(stock_field, 0) or 0)
        reserved = await reserved_qty(product_id, body.kondisi)
        available = max(0.0, current_stock - reserved)
        if qty > available:
            label = 'stok rusak' if body.kondisi == 'RUSAK' else 'stok'
            raise HTTPException(
                status_code=400,
                detail=f"{label.capitalize()} {prod['name']} tidak mencukupi. Tersedia untuk antrian {available:g}.",
            )

    op_now = legacy.operational_now()
    time = legacy.now_iso()
    operational_date = op_now.strftime('%Y-%m-%d')
    operation_id = legacy.new_id()
    unit_loading, queue_prefix = loading_unit_from_products(ordered_products)

    queue_floor = await legacy.max_suffix(
        db.surat_jalan,
        'antrian',
        f'{queue_prefix}-',
        {'operational_date': operational_date},
    )
    queue_number = await legacy.next_sequence(
        f'queue:{operational_date}:{queue_prefix}',
        queue_floor,
    )
    antrian = f'{queue_prefix}-{queue_number:03d}'

    bon_prefix = f"BM-{op_now.strftime('%Y%m%d')}-"
    bon_floor = await legacy.max_suffix(
        db.surat_jalan,
        'bon_no',
        bon_prefix,
        {'operational_date': operational_date},
    )
    bon_number = await legacy.next_sequence(
        f"bon-muat:{operational_date}",
        bon_floor,
    )
    bon_no = f'{bon_prefix}{bon_number:03d}'

    items = []
    total_berat = 0.0
    total_unit = 0.0
    for item in body.items:
        prod = products_by_id[item.productId]
        qty = float(item.qty)
        berat = float(prod.get('weight') or 0) * qty
        total_berat += berat
        total_unit += qty
        items.append(
            {
                'productId': prod['id'],
                'sku': prod.get('sku', ''),
                'name': prod['name'],
                'qty': qty,
                'unit': prod.get('unit', ''),
                'berat': berat,
                'location': prod.get('location', ''),
                'sec': prod.get('secondary', ''),
            }
        )

    transaction_ref = body.ref.strip() or f"OUT-{op_now.strftime('%Y%m%d%H%M%S%f')}"
    doc = {
        'id': legacy.new_id(),
        'operation_id': operation_id,
        'transaction_ref': transaction_ref,
        'no': '',
        'bon_no': bon_no,
        'antrian': antrian,
        'operational_date': operational_date,
        'time': time,
        'penerima': body.party.strip(),
        'pengambil': body.pengambil.strip(),
        'polisi': body.polisi.strip(),
        'operator': user['name'],
        'status': 'Menunggu',
        'ref': body.ref.strip(),
        'kondisi': body.kondisi,
        'keterangan': body.keterangan.strip(),
        'unit_loading': unit_loading,
        'items': items,
        'berat': total_berat,
        'unit': total_unit,
        'stock_committed': False,
        'created_at': time,
    }
    await db.surat_jalan.insert_one(dict(doc))
    return {'transactions': [], 'suratJalan': doc}


async def complete_loading(current: dict, user: dict):
    if current.get('status') == 'Selesai':
        return current
    if current.get('status') != 'Sedang Dimuat':
        raise HTTPException(status_code=409, detail='Klik Mulai Muat sebelum menyelesaikan pemuatan')

    # Dokumen lama sudah mengurangi stok saat dibuat. Jangan kurangi ulang.
    if 'stock_committed' not in current:
        await db.surat_jalan.update_one(
            {'id': current['id']},
            {'$set': {'status': 'Selesai', 'completed_at': legacy.now_iso()}},
        )
        return await db.surat_jalan.find_one({'id': current['id']}, {'_id': 0})

    if current.get('stock_committed') is True:
        await db.surat_jalan.update_one(
            {'id': current['id']},
            {'$set': {'status': 'Selesai', 'completed_at': legacy.now_iso()}},
        )
        return await db.surat_jalan.find_one({'id': current['id']}, {'_id': 0})

    op_now = legacy.operational_now()
    completion_time = legacy.now_iso()
    month_prefix = op_now.strftime('SJ-%Y%m')
    sj_floor = await legacy.max_suffix(db.surat_jalan, 'no', f'{month_prefix}-')
    sj_number = await legacy.next_sequence(f"surat-jalan:{op_now.strftime('%Y%m')}", sj_floor)
    sj_no = f'{month_prefix}-{sj_number:03d}'

    kondisi = current.get('kondisi', 'BAIK')
    stock_field = 'damaged' if kondisi == 'RUSAK' else 'stock'
    stock_changes = []
    txns = []

    try:
        for item in current.get('items', []):
            product_id = item.get('productId')
            qty = float(item.get('qty') or 0)
            if not product_id or qty <= 0:
                raise HTTPException(status_code=400, detail='Data barang pada antrian tidak lengkap')

            prod = await db.products.find_one({'id': product_id}, {'_id': 0})
            if not prod:
                raise HTTPException(status_code=404, detail=f"Produk {item.get('name', '')} tidak ditemukan")

            result = await db.products.update_one(
                {'id': product_id, stock_field: {'$gte': qty}},
                {'$inc': {stock_field: -qty}},
            )
            if result.matched_count == 0:
                raise HTTPException(
                    status_code=409,
                    detail=f"Stok {prod['name']} berubah atau tidak mencukupi. Periksa persediaan lalu coba kembali.",
                )
            stock_changes.append((product_id, stock_field, qty))
            txns.append(
                {
                    'id': legacy.new_id(),
                    'operation_id': current.get('operation_id') or uuid.uuid4().hex,
                    'time': completion_time,
                    'ref': current.get('transaction_ref') or current.get('ref') or sj_no,
                    'antrian': current.get('antrian', ''),
                    'type': 'KELUAR',
                    'kondisi': kondisi,
                    'product': prod['name'],
                    'sku': prod.get('sku', ''),
                    'change': -qty,
                    'penerima': current.get('penerima', '-'),
                    'polisi': current.get('polisi', ''),
                    'operator': user.get('name') or current.get('operator', ''),
                    'keterangan': current.get('keterangan', ''),
                    'surat_jalan_no': sj_no,
                    'bon_no': current.get('bon_no', ''),
                }
            )

        if txns:
            await db.transactions.insert_many([dict(txn) for txn in txns])

        result = await db.surat_jalan.update_one(
            {
                'id': current['id'],
                'stock_committed': False,
                'status': 'Sedang Dimuat',
            },
            {
                '$set': {
                    'status': 'Selesai',
                    'stock_committed': True,
                    'no': sj_no,
                    'completed_at': completion_time,
                }
            },
        )
        if result.matched_count == 0:
            raise HTTPException(status_code=409, detail='Status antrian berubah. Muat ulang halaman lalu coba lagi.')
    except Exception:
        operation_id = current.get('operation_id')
        if operation_id:
            await db.transactions.delete_many({'operation_id': operation_id, 'surat_jalan_no': sj_no})
        for product_id, field, qty in reversed(stock_changes):
            await db.products.update_one({'id': product_id}, {'$inc': {field: qty}})
        raise

    return await db.surat_jalan.find_one({'id': current['id']}, {'_id': 0})


app = FastAPI()

# Gunakan semua route lama kecuali dua route yang diubah untuk alur Bon Muat.
for route in legacy.api_router.routes:
    methods = set(getattr(route, 'methods', set()) or set())
    if route.path == '/transactions' and 'POST' in methods:
        continue
    if route.path == '/surat-jalan/{sj_id}/status' and 'PUT' in methods:
        continue
    app.router.routes.append(route)


@app.post('/transactions')
async def create_transaction(body: TxnBody, user: dict = Depends(legacy.require_write)):
    if body.type == 'MASUK':
        return await legacy.create_transaction(body, user)
    if body.type != 'KELUAR':
        raise HTTPException(status_code=400, detail='Jenis transaksi tidak valid')
    return await create_outgoing_transaction(body, user)


@app.put('/surat-jalan/{sj_id}/status')
async def update_sj_status(
    sj_id: str,
    body: SJStatusBody,
    user: dict = Depends(legacy.require_write),
):
    current = await db.surat_jalan.find_one({'id': sj_id}, {'_id': 0})
    if not current:
        raise HTTPException(status_code=404, detail='Antrian / surat jalan tidak ditemukan')

    if body.status == current.get('status'):
        return current

    if body.status == 'Sedang Dimuat':
        if current.get('status') != 'Menunggu':
            raise HTTPException(status_code=409, detail='Antrian tidak berada pada status Menunggu')
        await db.surat_jalan.update_one(
            {'id': sj_id, 'status': 'Menunggu'},
            {'$set': {'status': 'Sedang Dimuat', 'loading_started_at': legacy.now_iso()}},
        )
        return await db.surat_jalan.find_one({'id': sj_id}, {'_id': 0})

    if body.status == 'Selesai':
        return await complete_loading(current, user)

    raise HTTPException(status_code=400, detail='Perubahan status tidak diizinkan')


@app.on_event('startup')
async def startup_event():
    await legacy.initialize_app()


cors_origins = [
    origin.strip()
    for origin in os.environ.get('CORS_ORIGINS', 'http://localhost:3000').split(',')
    if origin.strip() and origin.strip() != '*'
]

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=cors_origins,
    allow_methods=['*'],
    allow_headers=['*'],
)
