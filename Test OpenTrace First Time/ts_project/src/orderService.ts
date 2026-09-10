export async function createOrderTransaction(orderId: string, amount: number) {
  const payload = JSON.stringify({ order_id: orderId, amount: amount });
  const res = await fetch('/payments', {
    method: 'POST',
    body: payload,
  });
  return await res.json();
}
