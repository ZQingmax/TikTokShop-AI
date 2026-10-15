"""Basic existing order API regression on independent PostgreSQL."""
from sqlalchemy import select
from app.models.user import User
from app.models.order import Order
from tests.conftest import TestSessionLocal


async def test_order_list_detail_status_and_auth(client):
    assert (await client.get('/api/v1/orders')).status_code == 403
    r = await client.post('/api/v1/auth/register', json={'username': 'orders@example.com', 'password': 'securepass123', 'nickname': 'Order User'})
    headers = {'Authorization': 'Bearer ' + r.json()['access_token']}
    async with TestSessionLocal() as db:
        order = Order(tiktok_order_id='TEST-ORDER-001', total_amount=25, currency='THB', status='pending', buyer_name='Test')
        db.add(order)
        await db.commit()
        id = str(order.id)
    assert (await client.get('/api/v1/orders?search=TEST-ORDER', headers=headers)).json()['total'] == 1
    assert (await client.get('/api/v1/orders/' + id, headers=headers)).json()['tiktok_order_id'] == 'TEST-ORDER-001'
    r = await client.put('/api/v1/orders/' + id + '/status', headers=headers, json={'status': 'confirmed', 'remark': 'API regression test'})
    assert r.status_code == 200
    assert (await client.get('/api/v1/orders/' + id, headers=headers)).json()['status'] == 'confirmed'
