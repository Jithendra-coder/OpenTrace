const apiClient = require('./client');

async function handleCheckout(order) {
  return await apiClient.post('/payments', {
    order_id: order.id,
    amount: order.totalCents,
  });
}

module.exports = { handleCheckout };
